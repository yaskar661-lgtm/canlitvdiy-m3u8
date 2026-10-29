import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import requests
from flask import Flask, Response, redirect, render_template_string, request

app = Flask(__name__)

# İstekler için ortak oturum (Session)
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

CANLITV_MAP = {
    "cartoon-network": (11233, "cartoon-network", "yayin2.canlitv.fun/live/cartoon-network.stream/playlist.m3u8"),
    "tivibu-spor": (12843, "tivibu-spor", "yayin2.canlitv.fun/live/tivibuspor.stream/playlist.m3u8"),
    "yaban-tv": (12044, "yaban-tv", "yayin1.canlitv.fun/canlitv/yabantv.stream/playlist.m3u8"),
    "tv-kayseri": (53, "tv-kayseri", "yayin1.canlitv.fun/canlitv/tvkayseri.stream/playlist.m3u8"),
    "koy-tv": (12013, "koy-tv", "yayin1.canlitv.fun/canlitv/koytv.stream/playlist.m3u8"),
}

# Dinamik domain için global değişken ve kilit
CURRENT_BASE_URL = "https://www.canlitv.diy"
domain_lock = threading.Lock()

def update_base_domain():
    """CanlıTV'nin güncel domain adresini otomatik olarak tespit eder."""
    global CURRENT_BASE_URL
    try:
        resp = SESSION.get("https://www.canlitv.diy/", timeout=10, allow_redirects=True)
        parsed_url = urlparse(resp.url)
        new_base = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        with domain_lock:
            CURRENT_BASE_URL = new_base
        print(f"[+] Aktif Domain Güncellendi: {CURRENT_BASE_URL}")
    except Exception as e:
        print(f"[-] Domain güncellenemedi, mevcut domain kullanılıyor: {CURRENT_BASE_URL} (Hata: {e})")

# Kanal verilerini ve hashleri anlık tutacağımız bellek (Cache) sözlüğü
STREAM_CACHE = {
    slug: {"url": None, "quality": "HD", "last_update": 0} 
    for slug in CANLITV_MAP.keys()
}
cache_lock = threading.Lock()

def get_canlitv_generic(slug, max_retries=2):
    """CanlıTV üzerinden dinamik hash parametresini yakalar."""
    if slug not in CANLITV_MAP: 
        return None, None
    
    pid, _, base_path = CANLITV_MAP[slug]
    
    with domain_lock:
        base_url = CURRENT_BASE_URL
        
    headers = {"Referer": f"{base_url}/{slug}"}
    
    for attempt in range(max_retries):
        try:
            resp = SESSION.get(f"{base_url}/player/index.php?id={pid}", headers=headers, timeout=15)
            if resp.status_code == 200:
                hash_match = re.search(r'[?&]hash=([a-f0-9]{32})', resp.text) or re.search(r'"hash":"([a-f0-9]{32})"', resp.text)
                if hash_match:
                    return f"https://{base_path}?hash={hash_match.group(1)}", "HD"
        except Exception:
            pass
        time.sleep(0.5)
        
    return None, None

def update_single_channel(slug):
    """Tek bir kanalın linkini çeker ve güvenli bir şekilde önbelleğe kaydeder."""
    stream_url, quality = get_canlitv_generic(slug)
    if stream_url:
        with cache_lock:
            STREAM_CACHE[slug] = {
                "url": stream_url,
                "quality": quality,
                "last_update": time.time()
            }
        print(f"[+] Güncellendi: {slug}")
    else:
        print(f"[-] Güncellenemedi: {slug}")

def run_bulk_update():
    """Önce güncel domaini kontrol eder, ardından ThreadPoolExecutor ile kanalları günceller."""
    print("[*] Toplu önbellek ve domain güncellemesi başlatıldı...")
    
    # 1. Adım: Önce ana domain adresinin değişip değişmediğini kontrol et
    update_base_domain()
    
    start_time = time.time()
    
    # 2. Adım: Kanalları paralel olarak güncelle
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(update_single_channel, CANLITV_MAP.keys())
        
    elapsed = time.time() - start_time
    print(f"[✔] Tüm işlemler bitti. Süre: {elapsed:.2f} saniye")

def update_cache_worker():
    """Arka planda periyodik olarak domaini ve tüm kanalların hash değerlerini günceller."""
    while True:
        run_bulk_update()
        print("[✔] Güncelleme döngüsü tamamlandı. 30 dakika bekleniyor...")
        time.sleep(1800) # 30 Dakika bekle

@app.route("/")
def index():
    host = request.host
    with domain_lock:
        current_domain = CURRENT_BASE_URL
        
    html = f"""
    <h2>CanlıTV Dinamik M3U Proxy Servisi</h2>
    <p><b>Aktif Domain:</b> {current_domain}</p>
    <p><b>M3U Çalma Listesi:</b> <a href="/playlist.m3u" target="_blank">http://{{{{ host }}}}/playlist.m3u</a></p>
    <p>
        <a href="/refresh" style="font-weight: bold; color: green; font-size: 15px;">🔄 Tüm Linkleri Şimdi Yenile (Refresh)</a>
    </p>
    <h3>Kanal Yönlendirme Linkleri (Direkt M3u8): (Toplam: {len(CANLITV_MAP)})</h3>
    <ul>
    {{% for slug in channels %}}
        <li><b>{{{{ slug }}}}</b>: <a href="/stream/{{{{ slug }}}}" target="_blank">http://{{{{ host }}}}/stream/{{{{ slug }}}}</a></li>
    {{% endfor %}}
    </ul>
    """
    return render_template_string(html, host=host, channels=CANLITV_MAP.keys())

@app.route("/refresh")
def refresh_cache():
    threading.Thread(target=run_bulk_update, daemon=True).start()
    return "Toplu önbellek ve domain güncellemesi arka planda başlatıldı! Birkaç saniye içinde güncellenecektir. <br><br><a href='/'>Ana Sayfaya Dön</a>"

@app.route("/playlist.m3u")
def playlist():
    m3u_content = "#EXTM3U\n"
    host = request.host
    
    with cache_lock:
        for slug in CANLITV_MAP.keys():
            data = STREAM_CACHE.get(slug)
            if data and data["url"]:
                proxy_stream_url = f"http://{host}/stream/{slug}"
                m3u_content += f'#EXTINF:-1 tvg-id="{slug}" tvg-name="{slug}",{slug.upper()} ({data["quality"]})\n'
                m3u_content += f"{proxy_stream_url}\n"
                
    return Response(m3u_content, mimetype="audio/x-mpegurl")

@app.route("/stream/<slug>")
def stream_redirect(slug):
    with cache_lock:
        data = STREAM_CACHE.get(slug)
        
    if data and data["url"]:
        return redirect(data["url"], code=302)
    else:
        url, quality = get_canlitv_generic(slug)
        if url:
            with cache_lock:
                STREAM_CACHE[slug] = {"url": url, "quality": quality, "last_update": time.time()}
            return redirect(url, code=302)
        return "Yayın şu an aktif değil veya hash alınamadı.", 404

if __name__ == "__main__":
    t = threading.Thread(target=update_cache_worker, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
