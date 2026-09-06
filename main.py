import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands, tasks
from discord import app_commands

# --- RENDER KEEP-ALIVE SUNUCUSU ---
LOG_CHANNEL_ID = 1544404573664313436  
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

# --- BUTONLU MESAİ PANELİ BİLEŞENİ ---
class MesaiControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Butonların süresi dolmaz

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
            title="🟢 Mesai Başlatıldı",
            description=f"{interaction.user.mention} mesaiye giriş yaptı.\n**Başlangıç:** {datetime.now().strftime('%H:%M:%S')}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

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
            # Molaya çıkış
            cursor.execute("UPDATE mesai SET mola_baslangic = ?, durum = 'molda' WHERE user_id = ?", (now_str, user_id))
            conn.commit()
            embed = discord.Embed(
                title="🟡 Molaya Çıkıldı",
                description=f"{interaction.user.mention} molaya ayrıldı.\n**Saat:** {now.strftime('%H:%M:%S')}",
                color=discord.Color.gold()
            )
            await interaction.response.send_message(embed=embed)

        elif durum == 'molda':
            # Moladan dönüş
            m_start = datetime.strptime(mola_baslangic, "%Y-%m-%d %H:%M:%S")
            mola_suresi = int((now - m_start).total_seconds())
            yeni_toplam_mola = (toplam_mola or 0) + mola_suresi

            cursor.execute("UPDATE mesai SET mola_baslangic = NULL, toplam_mola = ?, durum = 'acik' WHERE user_id = ?", (yeni_toplam_mola, user_id))
            conn.commit()
            embed = discord.Embed(
                title="🟢 Moladan Dönüldü",
                description=f"{interaction.user.mention} görevine geri döndü.\n**Mola Süresi:** {mola_suresi // 60} dakika",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)

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

        # Eğer moladaysa ve mesaiyi bitiriyorsa son molayı da ekle
        if durum == 'molda' and mola_baslangic_str:
            m_start = datetime.strptime(mola_baslangic_str, "%Y-%m-%d %H:%M:%S")
            toplam_mola += int((now - m_start).total_seconds())

        gecen_saniye = int((now - baslangic).total_seconds())
        net_mesai = max(0, gecen_saniye - toplam_mola)

        # Durumu kapat
        cursor.execute("UPDATE mesai SET durum = 'kapali' WHERE user_id = ?", (user_id,))
        
        # Toplam sürelere ekle
        cursor.execute("SELECT toplam_saniye FROM toplam_sureler WHERE user_id = ?", (user_id,))
        t_row = cursor.fetchone()
        mevcut_sure = t_row[0] if t_row else 0
        cursor.execute("INSERT OR REPLACE INTO toplam_sureler (user_id, toplam_saniye) VALUES (?, ?)", (user_id, mevcut_sure + net_mesai))

        conn.commit()
        conn.close()

        embed = discord.Embed(
            title="🔴 Mesai Tamamlandı",
            description=f"{interaction.user.mention} mesaiyi sonlandırdı.\n\n"
                        f"⏱️ **Net Mesai Süresi:** {format_seconds(net_mesai)}\n"
                        f"☕ **Mola Süresi:** {format_seconds(toplam_mola)}",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)


# --- BOT OLAYLARI & KOMUTLAR ---
@bot.event
async def on_ready():
    bot.add_view(MesaiControlView()) # Butonların bot yeniden başlasa da çalışmasını sağlar
    try:
        synced = await bot.tree.sync()
        print(f"Slash komutları senkronize edildi: {len(synced)} komut")
    except Exception as e:
        print(f"Komut senkronizasyon hatası: {e}")
    print(f"⚖️ DOJ Mesai Sistemi Aktif: {bot.user.name}")

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
        color=discord.Color.dark_navy()
    )
    # Türk Bayraklı & DOJ Görselli Görsel Kart
    embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/b/b4/Flag_of_Turkey.svg")
    embed.set_image(url="https://i.imgur.com/8Q9Z8Xp.png") # DOJ Banner Görseli
    embed.set_footer(text="Department of Justice • San Andreas Roleplay", icon_url=bot.user.avatar.url if bot.user.avatar else None)

    await interaction.channel.send(embed=embed, view=MesaiControlView())
    await interaction.response.send_message("✅ Mesai paneli bu kanala başarıyla kuruldu!", ephemeral=True)

@bot.tree.command(name="haftalik-rapor", description="Haftalık mesai sıralamasını gösterir.")
async def haftalik_rapor(interaction: discord.Interaction):
    conn = sqlite3.connect("mesai.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, toplam_saniye FROM toplam_sureler ORDER BY toplam_saniye DESC LIMIT 10")
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
