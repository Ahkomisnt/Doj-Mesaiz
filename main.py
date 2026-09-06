import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands, tasks
from discord import app_commands

# --- AYARLAR ---
LOG_CHANNEL_ID = 1544404573664313436  # Buraya log kanalının ID'sini yazın

# --- RENDER KEEP-ALIVE SUNUCUSU ---
app = Flask('')

@app.route('/')
def home():
    return "DOJ Mesai Botu 7/24 Aktif!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- BOT VE VERİTABANI KURULUMU ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

def init_db():
    conn = sqlite3.connect("mesai.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mesai (
            user_id INTEGER PRIMARY KEY,
            baslangic TEXT,
            mola_baslangic TEXT,
            toplam_mola INTEGER DEFAULT 0,
            durum TEXT DEFAULT 'kapali'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS toplam_sureler (
            user_id INTEGER PRIMARY KEY,
            toplam_saniye INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- YARDIMCI FONKSİYONLAR ---
def format_seconds(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours} saat {minutes} dakika"

async def log_gonder(embed):
    if LOG_CHANNEL_ID != 0:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)

# --- BUTONLU MESAİ PANELİ ---
class MesaiControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Mesai Başlat", style=discord.ButtonStyle.success, emoji="🟢", custom_id="btn_mesai_baslat")
    async def mesai_baslat(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect("mesai.db")
        cursor = conn.cursor()
        cursor.execute("SELECT durum FROM mesai WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if row and row[0] in ['acik', 'molda']:
            await interaction.response.send_message("❌ Zaten aktif bir mesainiz veya molanız bulunuyor!", ephemeral=True)
            conn.close()
            return

        cursor.execute("INSERT OR REPLACE INTO mesai (user_id, baslangic, mola_baslangic, toplam_mola, durum) VALUES (?, ?, NULL, 0, 'acik')", (user_id, now_str))
        conn.commit()
        conn.close()

        embed = discord.Embed(
            title="🟢 MESAİ BAŞLATILDI",
            description=f"**Memur:** {interaction.user.mention}\n**Başlangıç Saati:** {datetime.now().strftime('%H:%M:%S')}",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
        await interaction.response.send_message("✅ Mesainiz başlatıldı.", ephemeral=True)
        await log_gonder(embed)

    @discord.ui.button(label="Mola Ver / Mola Bitir", style=discord.ButtonStyle.primary, emoji="🟡", custom_id="btn_mola_toggle")
    async def mola_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect("mesai.db")
        cursor = conn.cursor()
        cursor.execute("SELECT baslangic, mola_baslangic, toplam_mola, durum FROM mesai WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if not row or row[3] == 'kapali':
            await interaction.response.send_message("❌ Aktif bir mesainiz bulunmuyor!", ephemeral=True)
            conn.close()
            return

        baslangic, mola_baslangic, toplam_mola, durum = row

        if durum == 'acik':
            cursor.execute("UPDATE mesai SET mola_baslangic = ?, durum = 'molda' WHERE user_id = ?", (now_str, user_id))
            conn.commit()
            embed = discord.Embed(
                title="🟡 MOLAYA ÇIKILDI",
                description=f"**Memur:** {interaction.user.mention}\n**Mola Başlangıç:** {now.strftime('%H:%M:%S')}",
                color=discord.Color.gold()
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            await interaction.response.send_message("☕ Molaya çıktınız.", ephemeral=True)
            await log_gonder(embed)

        elif durum == 'molda':
            m_start = datetime.strptime(mola_baslangic, "%Y-%m-%d %H:%M:%S")
            mola_suresi = int((now - m_start).total_seconds())
            yeni_toplam_mola = (toplam_mola or 0) + mola_suresi

            cursor.execute("UPDATE mesai SET mola_baslangic = NULL, toplam_mola = ?, durum = 'acik' WHERE user_id = ?", (yeni_toplam_mola, user_id))
            conn.commit()
            embed = discord.Embed(
                title="🟢 MOLADAN DÖNÜLDÜ",
                description=f"**Memur:** {interaction.user.mention}\n**Mola Süresi:** {mola_suresi // 60} dakika",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            await interaction.response.send_message("✅ Göreve geri döndünüz.", ephemeral=True)
            await log_gonder(embed)

        conn.close()

    @discord.ui.button(label="Mesai Bitir", style=discord.ButtonStyle.danger, emoji="🔴", custom_id="btn_mesai_bitir")
    async def mesai_bitir(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        now = datetime.now()

        conn = sqlite3.connect("mesai.db")
        cursor = conn.cursor()
        cursor.execute("SELECT baslangic, mola_baslangic, toplam_mola, durum FROM mesai WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if not row or row[3] == 'kapali':
            await interaction.response.send_message("❌ Aktif bir mesainiz bulunmuyor!", ephemeral=True)
            conn.close()
            return

        baslangic_str, mola_baslangic_str, toplam_mola, durum = row
        baslangic = datetime.strptime(baslangic_str, "%Y-%m-%d %H:%M:%S")

        if durum == 'molda' and mola_baslangic_str:
            m_start = datetime.strptime(mola_baslangic_str, "%Y-%m-%d %H:%M:%S")
            toplam_mola += int((now - m_start).total_seconds())

        gecen_saniye = int((now - baslangic).total_seconds())
        net_mesai = max(0, gecen_saniye - toplam_mola)

        cursor.execute("UPDATE mesai SET durum = 'kapali' WHERE user_id = ?", (user_id,))
        cursor.execute("SELECT toplam_saniye FROM toplam_sureler WHERE user_id = ?", (user_id,))
        t_row = cursor.fetchone()
        mevcut_sure = t_row[0] if t_row else 0
        cursor.execute("INSERT OR REPLACE INTO toplam_sureler (user_id, toplam_saniye) VALUES (?, ?)", (user_id, mevcut_sure + net_mesai))

        conn.commit()
        conn.close()

        embed = discord.Embed(
            title="🔴 MESAİ BİTİRİLDİ",
            description=f"**Memur:** {interaction.user.mention}\n\n"
                        f"⏱️ **Net Mesai Süresi:** `{format_seconds(net_mesai)}`\n"
                        f"☕ **Toplam Mola Süresi:** `{format_seconds(toplam_mola)}`",
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message("🔴 Mesainiz sonlandırıldı.", ephemeral=True)
        await log_gonder(embed)

# --- 3 SAATLİK OTOMATİK DM VE İNAKTİFLİK KONTROLÜ ---
@tasks.loop(minutes=15)
async def mesai_kontrol_gorevi():
    conn = sqlite3.connect("mesai.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, baslangic FROM mesai WHERE durum = 'acik'")
    rows = cursor.fetchall()

    now = datetime.now()
    for user_id, baslangic_str in rows:
        baslangic = datetime.strptime(baslangic_str, "%Y-%m-%d %H:%M:%S")
        gecen_saat = (now - baslangic).total_seconds() / 3600

        if gecen_saat >= 3:
            user = bot.get_user(user_id)
            if user:
                try:
                    await user.send("⚠️ **DOJ Mesai Uyarı:** 3 saattir aralıksız mesaide görünüyorsunuz. Hala aktif misiniz? Eğer mesainiz bittiyse paneli kullanarak bitirmeyi unutmayın!")
                except Exception:
                    pass
    conn.close()

# --- BOT OLAYLARI & KOMUTLAR ---
@bot.event
async def on_ready():
    bot.add_view(MesaiControlView())
    if not mesai_kontrol_gorevi.is_running():
        mesai_kontrol_gorevi.start()
    try:
        synced = await bot.tree.sync()
        print(f"Slash komutları senkronize edildi: {len(synced)} komut")
    except Exception as e:
        print(f"Komut senkronizasyon hatası: {e}")
    print(f"⚖️ DOJ Mesai Sistemi Aktif: {bot.user.name}")

# 1. MESAİ PANELİ
@bot.tree.command(name="mesai-paneli", description="DOJ Mesai Kontrol Panelini kanala kurar.")
@app_commands.checks.has_permissions(administrator=True)
async def mesai_paneli(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚖️ DEPARTMENT OF JUSTICE - MESAİ KONTROL PANELİ 🇹🇷",
        description=(
            "Aşağıdaki butonları kullanarak **Mesai** ve **Mola** durumlarınızı yönetebilirsiniz.\n\n"
            "🟢 **Mesai Başlat:** Göreve başlarken tıklayın.\n"
            "🟡 **Mola Ver / Bitir:** Mola başlatmak veya bitirmek için tıklayın.\n"
            "🔴 **Mesai Bitir:** Görevi sonlandırmak ve sürenizi kaydetmek için tıklayın.\n\n"
            "*İyi çalışmalar dileriz.*"
        ),
        color=discord.Color.from_str("#1B263B")
    )
    embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/b/b4/Flag_of_Turkey.svg")
    # Kırık imgur resmi çalışan sabit DOJ/Adalet bannerı ile değiştirildi
    embed.set_image(url="https://images.unsplash.com/photo-1589829545856-d10d557cf95f?q=80&w=1000&auto=format&fit=crop")
    embed.set_footer(text="Department of Justice • San Andreas Roleplay")

    await interaction.channel.send(embed=embed, view=MesaiControlView())
    await interaction.response.send_message("✅ Mesai paneli kuruldu!", ephemeral=True)

# 2. YÖNETİCİ: KULLANICI MESAİ VERİSİ SİL
@bot.tree.command(name="mesai-sil", description="[Yönetici] Bir kullanıcının aktif mesaisini iptal eder veya kaydını siler.")
@app_commands.checks.has_permissions(administrator=True)
async def mesai_sil(interaction: discord.Interaction, kullanici: discord.Member):
    conn = sqlite3.connect("mesai.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE mesai SET durum = 'kapali' WHERE user_id = ?", (kullanici.id,))
    conn.commit()
    conn.close()

    await interaction.response.send_message(f"🚨 {kullanici.mention} kullanıcısının aktif mesaisi yönetici tarafından sonlandırıldı.", ephemeral=True)

# 3. YÖNETİCİ: TÜM TOPLAM MESAİLERİ SIFIRLA (HAFTALIK SIFIRLAMA)
@bot.tree.command(name="mesai-sifirla", description="[Yönetici] Tüm haftalık mesai sürelerini sıfırlar.")
@app_commands.checks.has_permissions(administrator=True)
async def mesai_sifirla(interaction: discord.Interaction):
    conn = sqlite3.connect("mesai.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM toplam_sureler")
    cursor.execute("UPDATE mesai SET durum = 'kapali'")
    conn.commit()
    conn.close()

    await interaction.response.send_message("🧹 Tüm haftalık mesai verileri ve aktif mesailer başarıyla sıfırlandı!", ephemeral=True)

# 4. YÖNETİCİ: ELLE MESAİ EKLE
@bot.tree.command(name="mesai-ekle", description="[Yönetici] Bir kullanıcıya manuel olarak mesai süresi (dakika) ekler.")
@app_commands.checks.has_permissions(administrator=True)
async def mesai_ekle(interaction: discord.Interaction, kullanici: discord.Member, dakika: int):
    eklenecek_saniye = dakika * 60
    conn = sqlite3.connect("mesai.db")
    cursor = conn.cursor()
    cursor.execute("SELECT toplam_saniye FROM toplam_sureler WHERE user_id = ?", (kullanici.id,))
    row = cursor.fetchone()
    mevcut = row[0] if row else 0

    cursor.execute("INSERT OR REPLACE INTO toplam_sureler (user_id, toplam_saniye) VALUES (?, ?)", (kullanici.id, mevcut + eklenecek_saniye))
    conn.commit()
    conn.close()

    await interaction.response.send_message(f"✅ {kullanici.mention} kullanıcısına `{dakika}` dakika mesai süresi eklendi.", ephemeral=True)

# 5. AKTİF MESAİDEKİLERİ LİSTELE
@bot.tree.command(name="aktif-mesailer", description="Şu an aktif mesaide veya molada olan memurları gösterir.")
async def aktif_mesailer(interaction: discord.Interaction):
    conn = sqlite3.connect("mesai.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, durum, baslangic FROM mesai WHERE durum IN ('acik', 'molda')")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message("ℹ️ Şu an aktif mesaide olan memur bulunmuyor.", ephemeral=True)
        return

    embed = discord.Embed(title="📋 AKTİF MESAİDEKİ MEMURLAR", color=discord.Color.blue())
    metin = ""
    for u_id, durum, baslangic in rows:
        member = interaction.guild.get_member(u_id)
        name = member.mention if member else f"ID: {u_id}"
        durum_emoji = "🟢 Mesaide" if durum == 'acik' else "🟡 Molada"
        metin += f"{durum_emoji} | {name} - Başlangıç: `{baslangic[11:16]}`\n"

    embed.description = metin
    await interaction.response.send_message(embed=embed)

# 6. HAFTALIK RAPOR
@bot.tree.command(name="haftalik-rapor", description="Haftalık mesai sıralamasını gösterir.")
async def haftalik_rapor(interaction: discord.Interaction):
    conn = sqlite3.connect("mesai.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, toplam_saniye FROM toplam_sureler ORDER BY toplam_saniye DESC LIMIT 15")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message("📊 Henüz kaydedilmiş mesai verisi yok.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📊 DOJ HAFTALIK MESAİ LİDERLİK TABLOSU 🇹🇷",
        color=discord.Color.gold()
    )
    
    liste_metni = ""
    for index, (user_id, saniye) in enumerate(rows, start=1):
        member = interaction.guild.get_member(user_id)
        name = member.mention if member else f"Kullanıcı ({user_id})"
        liste_metni += f"**{index}.** {name} — `{format_seconds(saniye)}`\n"

    embed.description = liste_metni
    await interaction.response.send_message(embed=embed)

# BOT RUN
keep_alive()
token = os.getenv("DISCORD_TOKEN")
if token:
    bot.run(token)
else:
    print("❌ HATA: DISCORD_TOKEN bulunamadı.")
