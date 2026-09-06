import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
import discord
from discord.ext import commands, tasks
from discord import app_commands

# --- INTENTS VE BOT AYARLARI ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class MesaiBotu(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.active_sessions = {}  # {user_id: {"start_time": datetime, "log_msg_id": int}}

bot = MesaiBotu()

# --- DOJ TEMALI EMBED RENKLERİ VE AYARLAR ---
DOJ_COLOR = 0x1A2B4C  # Lacivert / Resmi DOJ Tonu
LOG_CHANNEL_ID = 123456789012345678  # !!! BURAYA LOG KANALININ ID'SİNİ YAZIN !!!
DB_FILE = "mesai_verileri.db"

# --- VERİTABANI KURULUMU ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Kalıcı mesai kayıtları tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mesailer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            start_time TEXT,
            end_time TEXT,
            duration_seconds REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- YARDIMCI FONKSİYONLAR ---
def format_duration(seconds):
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours} Saat, {minutes} Dakika, {secs} Saniye"

def add_shift_to_db(user_id, start_time, end_time, duration):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO mesailer (user_id, start_time, end_time, duration_seconds)
        VALUES (?, ?, ?, ?)
    ''', (user_id, start_time.strftime("%Y-%m-%d %H:%M:%S"), end_time.strftime("%Y-%m-%d %H:%M:%S"), duration))
    conn.commit()
    conn.close()

# --- BOT HAZIR OLDUĞUNDA ---
@bot.event
async def on_ready():
    print(f"⚖️ {bot.user.name} DOJ Mesai Takip Sistemi Aktif!")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} Slash Komutu Senkronize Edildi.")
    except Exception as e:
        print(f"❌ Komut senkronizasyon hatası: {e}")
    
    if not check_inactivity.is_running():
        check_inactivity.start()

# --- SLASH KOMUTLARI ---

# 1. MESAİ BAŞLAT
@bot.tree.command(name="mesai-baslat", description="DOJ bünyesindeki mesainizi başlatır.")
async def mesai_baslat(interaction: discord.Interaction):
    user_id = interaction.user.id

    if user_id in bot.active_sessions:
        embed = discord.Embed(
            title="⚠️ Aktif Mesai Bulundu",
            description="Zaten devam eden bir mesainiz bulunmaktadır. Önce mevcut mesaiyi bitirmelisiniz.",
            color=0xE74C3C
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    now = datetime.now()
    bot.active_sessions[user_id] = {"start_time": now, "log_msg_id": None}

    embed_user = discord.Embed(
        title="🏛️ DEPARTMENT OF JUSTICE — MESAİ BAŞLADI",
        description=f"Sayın **{interaction.user.display_name}**, mesainiz başarıyla sisteme işlenmiştir.",
        color=DOJ_COLOR,
        timestamp=now
    )
    embed_user.add_field(name="👤 Görevli Personel", value=interaction.user.mention, inline=True)
    embed_user.add_field(name="⏰ Başlangıç Saati", value=now.strftime("%H:%M:%S"), inline=True)
    embed_user.set_footer(text="DOJ Mesai & Denetim Sistemi")
    
    await interaction.response.send_message(embed=embed_user)

    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed_log = discord.Embed(
            title="📥 MESAİ GİRİŞ KAYDI",
            color=0x2ECC71,
            timestamp=now
        )
        embed_log.add_field(name="Personel", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed_log.add_field(name="Giriş Zamanı", value=now.strftime("%d/%m/%Y - %H:%M:%S"), inline=False)
        embed_log.set_thumbnail(url=interaction.user.display_avatar.url)
        log_msg = await log_channel.send(embed=embed_log)
        bot.active_sessions[user_id]["log_msg_id"] = log_msg.id

# 2. MESAİ BİTİR
@bot.tree.command(name="mesai-bitir", description="Devam eden mesainizi sonlandırır ve kaydeder.")
async def mesai_bitir(interaction: discord.Interaction):
    user_id = interaction.user.id

    if user_id not in bot.active_sessions:
        embed = discord.Embed(
            title="❌ Aktif Mesai Bulunamadı",
            description="Şu anda aktif bir mesainiz bulunmamaktadır.",
            color=0xE74C3C
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    start_time = bot.active_sessions[user_id]["start_time"]
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Veritabanına Kalıcı Kaydet
    add_shift_to_db(user_id, start_time, end_time, duration)
    del bot.active_sessions[user_id]

    embed_user = discord.Embed(
        title="🏛️ DEPARTMENT OF JUSTICE — MESAİ BİTTİ",
        description=f"Sayın **{interaction.user.display_name}**, mesainiz başarıyla sonlandırılmıştır.",
        color=DOJ_COLOR,
        timestamp=end_time
    )
    embed_user.add_field(name="👤 Görevli Personel", value=interaction.user.mention, inline=True)
    embed_user.add_field(name="⏱️ Toplam Süre", value=format_duration(duration), inline=True)
    embed_user.set_footer(text="DOJ Mesai & Denetim Sistemi")

    await interaction.response.send_message(embed=embed_user)

    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed_log = discord.Embed(
            title="📤 MESAİ ÇIKIŞ KAYDI",
            color=0xE74C3C,
            timestamp=end_time
        )
        embed_log.add_field(name="Personel", value=f"{interaction.user.mention}", inline=True)
        embed_log.add_field(name="Toplam Çalışma", value=format_duration(duration), inline=True)
        embed_log.set_thumbnail(url=interaction.user.display_avatar.url)
        await log_channel.send(embed=embed_log)

# 3. AKTİF MESAİLERİ RAPORLA
@bot.tree.command(name="rapor", description="Anlık olarak aktif mesaide olan tüm personeli listeler.")
async def rapor(interaction: discord.Interaction):
    if not bot.active_sessions:
        embed = discord.Embed(
            title="📋 Aktif Mesai Raporu",
            description="Şu anda aktif mesaide olan personel bulunmamaktadır.",
            color=DOJ_COLOR
        )
        await interaction.response.send_message(embed=embed)
        return

    embed = discord.Embed(
        title="🏛️ DOJ — AKTİF MESAİDEKİ PERSONEL",
        color=DOJ_COLOR,
        timestamp=datetime.now()
    )

    for uid, data in bot.active_sessions.items():
        member = interaction.guild.get_member(uid)
        elapsed = (datetime.now() - data["start_time"]).total_seconds()
        embed.add_field(
            name=f"⚖️ {member.display_name if member else 'Bilinmeyen'}",
            value=f"• **Giriş:** {data['start_time'].strftime('%H:%M:%S')}\n• **Geçen Süre:** {format_duration(elapsed)}",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

# 4. HAFTALIK SIRALAMA RAPORU (Veritabanından Çeker)
@bot.tree.command(name="haftalik-rapor", description="Sistemdeki tüm zamanların/haftalık mesailerini sıralar.")
async def haftalik_rapor(interaction: discord.Interaction):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, SUM(duration_seconds) as total 
        FROM mesailer 
        GROUP BY user_id 
        ORDER BY total DESC
    ''')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        embed = discord.Embed(
            title="📊 Mesai Liderlik Tablosu",
            description="Henüz kaydedilmiş bir mesai verisi bulunmuyor.",
            color=DOJ_COLOR
        )
        await interaction.response.send_message(embed=embed)
        return

    embed = discord.Embed(
        title="🏛️ DEPARTMENT OF JUSTICE — MESAİ LİDERLİK TABLOSU",
        description="En yüksek çalışma süresine sahip personeller sıralanmıştır:",
        color=DOJ_COLOR,
        timestamp=datetime.now()
    )

    medals = ["🥇", "🥈", "🥉"]
    for idx, (uid, total_sec) in enumerate(rows, 1):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"Kullanıcı ({uid})"
        prefix = medals[idx-1] if idx <= 3 else f"**#{idx}**"
        embed.add_field(
            name=f"{prefix} {name}",
            value=f"➡️ **Toplam Süre:** {format_duration(total_sec)}",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

# 5. KİŞİNİN MESAİSİNİ GÖRÜNTÜLE VE SİL
@bot.tree.command(name="mesai-sil", description="Bir kullanıcının kaydolmuş mesailerini gösterir ve seçilen ID'deki mesaiyi siler.")
@app_commands.describe(kullanici="Mesaisi yönetilecek kişi", kayit_id="Silinmek istenen mesainin ID numarası (Boş bırakırsanız liste atar)")
async def mesai_sil(interaction: discord.Interaction, kullanici: discord.Member, kayit_id: int = None):
    # Yönetici yetkisi denetimi
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Bu komutu kullanmak için Yönetici yetkisine sahip olmalısınız.", ephemeral=True)
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Eğer ID girildiyse direkt o kaydı sil
    if kayit_id is not None:
        cursor.execute("DELETE FROM mesailer WHERE id = ? AND user_id = ?", (kayit_id, kullanici.id))
        conn.commit()
        conn.close()
        embed = discord.Embed(
            title="🗑️ Mesai Kaydı Silindi",
            description=f"{kullanici.mention} kullanıcısına ait **ID: {kayit_id}** numaralı mesai kaydı veritabanından tamamen silindi.",
            color=0xE74C3C
        )
        await interaction.response.send_message(embed=embed)
        return

    # ID girilmediyse kullanıcının son mesailerini detaylı listele
    cursor.execute("SELECT id, start_time, end_time, duration_seconds FROM mesailer WHERE user_id = ? ORDER BY id DESC LIMIT 10", (kullanici.id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message(f"❌ {kullanici.mention} kullanıcısına ait kaydedilmiş mesai bulunamadı.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"📋 {kullanici.display_name} — Mesai Detay Geçmişi",
        description="Silmek istediğiniz mesainin ID numarasını öğrenip `/mesai-sil kullanici: @kisi kayit_id: ID` şeklinde silme yapabilirsiniz:",
        color=DOJ_COLOR
    )

    for row in rows:
        m_id, start, end, dur = row
        embed.add_field(
            name=f"🆔 Kayıt ID: {m_id}",
            value=f"• **Giriş:** {start}\n• **Çıkış:** {end}\n• **Süre:** {format_duration(dur)}",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

# 6. TÜM MESAİLERİ SIFIRLA
@bot.tree.command(name="mesai-sifirla", description="Tüm veritabanındaki mesai kayıtlarını tamamen temizler.")
async def mesai_sifirla(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Bu komutu kullanmak için Yönetici yetkisine sahip olmalısınız.", ephemeral=True)
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM mesailer")
    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="⚠️ TÜM MESAİ VERİLERİ SIFIRLANDI",
        description="Veritabanındaki tüm mesai geçmişi ve süre kayıtları başarıyla sıfırlandı.",
        color=0xE74C3C,
        timestamp=datetime.now()
    )
    await interaction.response.send_message(embed=embed)

# --- OTOMATİK İNAKTİFLİK VE DM KONTROLÜ (3 Saat Sonra Control) ---
@tasks.loop(minutes=1)
async def check_inactivity():
    now = datetime.now()
    for uid, data in list(bot.active_sessions.items()):
        start_time = data["start_time"]
        
        # 3 Saat Doldu Mu?
        if now - start_time >= timedelta(hours=3) and not data.get("prompted"):
            bot.active_sessions[uid]["prompted"] = True
            
            user = bot.get_user(uid)
            if user:
                try:
                    embed_dm = discord.Embed(
                        title="⚠️ DOJ MESAİ DENETİM BİLDİRİMİ",
                        description="3 saattir aktif mesaide görünüyorsunuz.\n\nMesainiz devam ediyor mu? **10 dakika** içinde bu mesaja `evet` yazarak yanıt vermezseniz mesainiz otomatik olarak kapatılacaktır.",
                        color=0xF1C40F
                    )
                    await user.send(embed=embed_dm)

                    def check(m):
                        return m.author.id == uid and isinstance(m.channel, discord.DMChannel) and m.content.lower() == "evet"

                    try:
                        await bot.wait_for("message", check=check, timeout=600.0)  # 10 Dk Bekle
                        
                        await user.send("✅ Mesainiz onaylandı ve devam ettiriliyor.")
                        bot.active_sessions[uid]["start_time"] = datetime.now()
                        bot.active_sessions[uid]["prompted"] = False

                    except asyncio.TimeoutError:
                        if uid in bot.active_sessions:
                            end_time = datetime.now()
                            duration = (end_time - start_time).total_seconds()
                            
                            # Otomatik veritabanına kaydet
                            add_shift_to_db(uid, start_time, end_time, duration)
                            del bot.active_sessions[uid]

                            await user.send("🛑 **10 dakika boyunca yanıt vermediğiniz için mesainiz otomatik olarak sonlandırıldı ve kaydedildi.**")
                            
                            log_channel = bot.get_channel(1544404573664313436)
                            if log_channel:
                                embed_auto_log = discord.Embed(
                                    title="⚠️ OTOMATİK MESAİ KAPATMA",
                                    description=f"{user.mention} 3 saatlik kontrol bildirimine yanıt vermediği için mesaisi sistem tarafından kapatıldı.",
                                    color=0xE67E22,
                                    timestamp=end_time
                                )
                                await log_channel.send(embed=embed_auto_log)

                except Exception as e:
                    print(f"DM Gönderme hatası ({uid}): {e}")

token = os.getenv("DISCORD_TOKEN")
if token:
    bot.run(token)
else:
    print("❌ HATA: DISCORD_TOKEN bulunamadı.")