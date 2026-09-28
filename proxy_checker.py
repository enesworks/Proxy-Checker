#!/usr/bin/env python3
"""Proxy listesini kontrol eder ve çalışanları ayrı bir dosyaya yazar."""

import argparse
import asyncio
import colorsys
import ipaddress
import os
import platform
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, font as tkfont, ttk
except ImportError:
    tk = None

try:
    import aiohttp
    from aiohttp_socks import ProxyConnector
except ImportError:
    print("Gerekli paketler eksik. Kurulum: pip install aiohttp aiohttp-socks")
    raise SystemExit(1)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.table import Table
    from rich.text import Text
except ImportError:
    Console = None

console = Console(
    color_system="truecolor" if sys.stdout.isatty() else None,
    legacy_windows=False,
) if Console and platform.system() != "Windows" else None

TIMEOUT = 5
ESZAMANLILIK = 300
TEST_URL = "https://api.ipify.org?format=json"


def yaz(metin, renk=None):
    if console:
        console.print(metin, style=renk, markup=False)
    else:
        print(metin)


def baslik_goster():
    if not console:
        print("\n========== ENESWORKS | PROXY CHECKER ==========\n")
        return

    baslik = Text(justify="center")
    renkler = (
        "#ff4dbe", "#ff72cf", "#f885f5", "#c77dff", "#a484ff",
        "#759bff", "#4db8ff", "#37d9ed", "#43f5c4",
    )
    for harf, renk in zip("ENESWORKS", renkler):
        baslik.append(harf, style=f"bold {renk}")
        baslik.append(" ")
    baslik.append("\n")
    baslik.append("P R O X Y   C H E C K E R", style="bold #a6b8d1")
    baslik.append("\nTXT dosyanı seç  •  proxy'leri tara  •  çalışanları kaydet", style="#91a5be")
    console.print()
    console.print(Panel.fit(baslik, border_style="#8d7dff", padding=(1, 3)))
    console.print()


def sor(metin):
    if console:
        return console.input(f"[bold #53d8ff]{metin}[/] ")
    return input(f"{metin} ")


def masaustu_yolu():
    home = Path.home()
    if platform.system() == "Windows":
        for yol in (home / "Desktop", home / "OneDrive" / "Desktop", home / "Masaüstü"):
            if yol.is_dir():
                return yol
    elif platform.system() == "Darwin":
        return home / "Desktop"
    else:
        try:
            import subprocess

            sonuc = subprocess.run(
                ["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=3
            )
            if sonuc.returncode == 0 and sonuc.stdout.strip():
                return Path(sonuc.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    return home / "Desktop"


def proxy_oku(satir):
    satir = satir.strip()
    if not satir or satir.startswith("#"):
        return None

    tip = "auto"
    if "://" in satir:
        protokol, satir = satir.split("://", 1)
        protokol = protokol.lower()
        if protokol in ("socks4", "socks5"):
            tip = protokol
        elif protokol in ("http", "https"):
            tip = protokol
        else:
            return None

    parcalar = satir.rsplit(":", 3)
    if len(parcalar) not in (2, 4):
        return None

    host, port = parcalar[:2]
    kullanici, parola = (None, None)
    if len(parcalar) == 4:
        kullanici, parola = parcalar[2:]
        if not kullanici:
            return None

    try:
        adres = ipaddress.ip_address(host.strip("[]"))
        port_no = int(port)
    except ValueError:
        return None

    if adres.version != 4 or not (1 <= port_no <= 65535) or not adres.is_global:
        return None

    return {
        "host": str(adres),
        "port": port_no,
        "tip": tip,
        "kullanici": kullanici,
        "parola": parola,
    }


def listeyi_oku(dosya):
    proxyler = []
    gorulen = set()
    try:
        with dosya.open("r", encoding="utf-8-sig", errors="replace") as kaynak:
            for satir in kaynak:
                proxy = proxy_oku(satir)
                if proxy:
                    anahtar = tuple(proxy.values())
                    if anahtar not in gorulen:
                        gorulen.add(anahtar)
                        proxyler.append(proxy)
    except OSError as hata:
        yaz(f"Dosya okunamadı: {hata}", "bold red")
        return []
    return proxyler


def dosya_ara(giris):
    giris = giris.strip().strip('"')
    if not giris:
        return []
    verilen_yol = Path(giris).expanduser()
    if verilen_yol.is_file():
        return [verilen_yol]
    if "/" in giris or "\\" in giris:
        return []

    dosya_adi = giris if giris.lower().endswith(".txt") else giris + ".txt"
    atlanacaklar = {
        "appdata", ".codex", ".git", "node_modules", "__pycache__",
        "scoop", "venv", ".venv", "packages", "windowsapps",
    }
    bulunanlar = []
    for kok, klasorler, dosyalar in os.walk(Path.home()):
        klasorler[:] = [
            ad for ad in klasorler
            if ad.lower() not in atlanacaklar and not ad.startswith(".")
        ]
        if dosya_adi.casefold() in {ad.casefold() for ad in dosyalar}:
            bulunanlar.append(Path(kok) / next(
                ad for ad in dosyalar if ad.casefold() == dosya_adi.casefold()
            ))
    return sorted(bulunanlar)


def dosya_bul():
    giris = sor("TXT dosyanızın adını veya yolunu girin:").strip().strip('"')
    if not giris:
        yaz("Dosya adı boş bırakılamaz.", "bold red")
        return None

    yaz(f"'{giris}' kişisel klasörünüzde aranıyor...", "#91a5be")
    bulunanlar = dosya_ara(giris)

    if not bulunanlar:
        yaz("Dosya bulunamadı. Dosya adını veya tam yolunu kontrol edin.", "bold red")
        return None
    if len(bulunanlar) == 1:
        yaz(f"Dosya bulundu: {bulunanlar[0]}", "bold green")
        return bulunanlar[0]

    yaz("Aynı adda birden fazla dosya bulundu:", "bold yellow")
    for sira, dosya in enumerate(bulunanlar, 1):
        yaz(f"{sira}) {dosya}")
    while True:
        secim = sor("Kullanılacak dosyanın numarası:").strip()
        if secim.isdigit() and 1 <= int(secim) <= len(bulunanlar):
            return bulunanlar[int(secim) - 1]
        yaz("Listeden geçerli bir numara girin.", "bold red")


async def tek_protokol_test_et(proxy, tip):
    adres = f"{proxy['host']}:{proxy['port']}"
    kimlik = proxy["kullanici"]
    parola = proxy["parola"]
    auth = aiohttp.BasicAuth(kimlik, parola or "") if kimlik is not None else None
    proxy_url = f"{tip}://{adres}"
    if tip in ("socks4", "socks5"):
        from urllib.parse import quote

        kimlik_kismi = ""
        if kimlik is not None:
            kimlik_kismi = f"{quote(kimlik, safe='')}:{quote(parola or '', safe='')}@"
        proxy_url = f"{tip}://{kimlik_kismi}{adres}"

    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        if tip in ("socks4", "socks5"):
            connector = ProxyConnector.from_url(proxy_url)
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as oturum:
                async with oturum.get(TEST_URL) as yanit:
                    if yanit.status == 200:
                        veri = await yanit.json(content_type=None)
                        ipaddress.ip_address(veri["ip"])
                        return True
        else:
            async with aiohttp.ClientSession(timeout=timeout) as oturum:
                async with oturum.get(TEST_URL, proxy=proxy_url, proxy_auth=auth) as yanit:
                    if yanit.status == 200:
                        veri = await yanit.json(content_type=None)
                        ipaddress.ip_address(veri["ip"])
                        return True
    except Exception:
        # Bozuk veya erken kapanan proxy bağlantıları testi durdurmasın.
        pass
    return False


async def proxy_test_et(proxy):
    baslangic = time.monotonic()
    tipler = ("http", "socks5", "socks4") if proxy["tip"] == "auto" else (proxy["tip"],)
    for tip in tipler:
        if await tek_protokol_test_et(proxy, tip):
            return {
                **proxy,
                "tip": tip,
                "gecikme": round((time.monotonic() - baslangic) * 1000),
            }
    return None


def sonuclari_kaydet(sonuclar, masaustu):
    zaman = datetime.now().strftime("%Y%m%d_%H%M%S")
    hedef = masaustu / f"canli_proxy_{zaman}.txt"
    with hedef.open("w", encoding="utf-8") as cikti:
        for proxy in sonuclar:
            cikti.write(f"{proxy['host']}:{proxy['port']}\n")
    return hedef


async def hepsini_test_et(proxyler, on_progress=None, stop_event=None):
    sonuclar = []
    sem = asyncio.Semaphore(ESZAMANLILIK)
    kilit = asyncio.Lock()
    tamamlanan = 0
    progress = None
    task_id = None

    async def kontrol(proxy):
        nonlocal tamamlanan
        async with sem:
            if stop_event is not None and stop_event.is_set():
                return
            sonuc = await proxy_test_et(proxy)
        async with kilit:
            tamamlanan += 1
            if sonuc:
                sonuclar.append(sonuc)
            if on_progress:
                on_progress(tamamlanan, len(proxyler), len(sonuclar), sonuc)
            elif progress:
                progress.update(
                    task_id, advance=1,
                    description=f"[bold #53d8ff]Taranıyor[/]  [bold #43f5c4]Çalışan: {len(sonuclar)}[/]",
                )
            elif sonuc:
                yaz(f"[{tamamlanan}/{len(proxyler)}] Çalışıyor: {proxy['host']}:{proxy['port']}")
            elif tamamlanan % 100 == 0 or tamamlanan == len(proxyler):
                yaz(f"[{tamamlanan}/{len(proxyler)}] Kontrol edildi")

    if console and on_progress is None:
        progress = Progress(
            SpinnerColumn(style="#ff72cf"),
            TextColumn("{task.description}"),
            BarColumn(complete_style="#8d7dff", finished_style="#43f5c4"),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        )
        with progress:
            task_id = progress.add_task("[bold #53d8ff]Taranıyor[/]", total=len(proxyler))
            await asyncio.gather(*(kontrol(proxy) for proxy in proxyler))
    else:
        await asyncio.gather(*(kontrol(proxy) for proxy in proxyler))

    sonuclar.sort(key=lambda p: (ipaddress.ip_address(p["host"]), p["port"]))
    return sonuclar


def sonuc_goster(sonuclar, hedef):
    if not console:
        yaz(f"\n{len(sonuclar)} çalışan proxy kaydedildi: {hedef}")
        return

    tablo = Table(title="Çalışan Proxy'ler", border_style="#8d7dff", header_style="bold #53d8ff")
    tablo.add_column("Proxy", style="#e8efff")
    tablo.add_column("Tür", style="#c77dff")
    tablo.add_column("Gecikme", justify="right", style="#43f5c4")
    for proxy in sonuclar[:10]:
        tablo.add_row(
            f"{proxy['host']}:{proxy['port']}", proxy["tip"], f"{proxy['gecikme']} ms"
        )
    console.print(tablo)
    if len(sonuclar) > 10:
        yaz(f"İlk 10 sonuç gösteriliyor. Toplam: {len(sonuclar)}", "#91a5be")
    console.print(Panel.fit(
        Text(f"{len(sonuclar)} çalışan proxy\n{hedef}", style="bold #43f5c4"),
        title="KAYDEDİLDİ", border_style="#43f5c4",
    ))


class ProxyPanel:
    BG = "#090e1b"
    CARD = "#111b2d"
    TEXT = "#e9f2ff"
    MUTED = "#90a3bc"
    CYAN = "#43d9ff"
    GREEN = "#41efb6"
    PINK = "#ff55ba"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ENESWORKS | Proxy Checker")
        self.root.geometry("920x720")
        self.root.minsize(790, 680)
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self.kapat)

        self.events = queue.SimpleQueue()
        self.stop_event = threading.Event()
        self.busy = False
        self.started = None
        self.output_path = None
        self.header_items = []
        self.header_line = []

        self.header = tk.Canvas(self.root, height=143, bg=self.BG, highlightthickness=0)
        self.header.pack(fill="x", padx=20, pady=(13, 3))
        self.header.bind("<Configure>", self.baslik_ciz)

        input_card = tk.Frame(self.root, bg=self.CARD, highlightbackground="#2b4161", highlightthickness=1)
        input_card.pack(fill="x", padx=22, pady=(4, 12))
        tk.Label(input_card, text="PROXY LİSTESİ  ·  TXT DOSYASI", bg=self.CARD,
                 fg=self.CYAN, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(12, 5))
        input_row = tk.Frame(input_card, bg=self.CARD)
        input_row.pack(fill="x", padx=16, pady=(0, 14))
        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(input_row, textvariable=self.path_var, bg="#0b1424",
                                   fg=self.TEXT, insertbackground=self.CYAN, relief="flat",
                                   font=("Segoe UI", 12), highlightbackground="#37506f",
                                   highlightcolor=self.CYAN, highlightthickness=1)
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.path_entry.bind("<Return>", lambda _event: self.baslat())
        self.dosya_btn = tk.Button(input_row, text="DOSYA SEÇ", command=self.dosya_sec,
                                   bg="#243b5b", fg=self.TEXT, activebackground="#31547d",
                                   activeforeground=self.TEXT, relief="flat", cursor="hand2",
                                   font=("Segoe UI", 9, "bold"), padx=15, pady=8)
        self.dosya_btn.pack(side="left", padx=(9, 0))
        self.start_btn = tk.Button(input_row, text="TARAMAYI BAŞLAT", command=self.baslat,
                                   bg="#6846ce", fg="white", activebackground="#815cf0",
                                   activeforeground="white", relief="flat", cursor="hand2",
                                   font=("Segoe UI", 9, "bold"), padx=15, pady=8)
        self.start_btn.pack(side="left", padx=(9, 0))

        stats = tk.Frame(self.root, bg=self.BG)
        stats.pack(fill="x", padx=22, pady=(0, 10))
        self.scanned_value = self.istatistik(stats, "TARANAN", "0 / 0", self.CYAN)
        self.live_value = self.istatistik(stats, "ÇALIŞAN", "0", self.GREEN)
        self.time_value = self.istatistik(stats, "SÜRE", "00:00", self.PINK)

        progress_row = tk.Frame(self.root, bg=self.BG)
        progress_row.pack(fill="x", padx=22, pady=(0, 10))
        self.progress = tk.Canvas(progress_row, height=12, bg="#1b2941", highlightthickness=0)
        self.progress.pack(side="left", fill="x", expand=True, pady=9)
        self.stop_btn = tk.Button(progress_row, text="DURDUR", command=self.durdur,
                                  bg="#422737", fg="#ff9bbd", activebackground="#603048",
                                  activeforeground="white", relief="flat", cursor="hand2",
                                  font=("Segoe UI", 9, "bold"), padx=16, pady=5,
                                  state="disabled")
        self.stop_btn.pack(side="left", padx=(12, 0))

        results_card = tk.Frame(self.root, bg=self.CARD, highlightbackground="#2b4161", highlightthickness=1)
        results_card.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        tk.Label(results_card, text="CANLI SONUÇLAR", bg=self.CARD, fg=self.CYAN,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(11, 7))
        table_row = tk.Frame(results_card, bg=self.CARD)
        table_row.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Results.Treeview", background=self.CARD, foreground=self.TEXT,
                        fieldbackground=self.CARD, borderwidth=0, rowheight=27,
                        font=("Segoe UI", 10))
        style.configure("Results.Treeview.Heading", background="#1d2c46", foreground=self.CYAN,
                        borderwidth=0, relief="flat", font=("Segoe UI", 9, "bold"))
        style.map("Results.Treeview", background=[("selected", "#30577a")],
                  foreground=[("selected", "white")])
        style.configure("Dark.Vertical.TScrollbar", background="#294365",
                        troughcolor=self.CARD, arrowcolor=self.CYAN,
                        bordercolor=self.CARD, relief="flat")
        self.table = ttk.Treeview(table_row, columns=("adres", "tip", "gecikme"),
                                  show="headings", style="Results.Treeview", selectmode="browse",
                                  height=5)
        self.table.heading("adres", text="IP : PORT")
        self.table.heading("tip", text="TÜR")
        self.table.heading("gecikme", text="GECİKME")
        self.table.column("adres", width=410, anchor="w")
        self.table.column("tip", width=160, anchor="center")
        self.table.column("gecikme", width=150, anchor="e")
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_row, orient="vertical", command=self.table.yview,
                                  style="Dark.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scrollbar.set)

        footer = tk.Frame(self.root, bg=self.BG)
        footer.pack(fill="x", padx=22, pady=(0, 15))
        self.status_var = tk.StringVar(value="Hazır · TXT dosyasının adını yazın veya dosya seçin.")
        tk.Label(footer, textvariable=self.status_var, bg=self.BG, fg=self.MUTED,
                 anchor="w", font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True)
        self.output_btn = tk.Button(footer, text="SONUCU AÇ", command=self.sonucu_ac,
                                    bg="#164d48", fg=self.GREEN, activebackground="#216d64",
                                    activeforeground="white", relief="flat", cursor="hand2",
                                    font=("Segoe UI", 9, "bold"), padx=15, pady=7,
                                    state="disabled")
        self.output_btn.pack(side="right")

        self.root.after(70, self.renkleri_canlandir)
        self.root.after(80, self.olaylari_isle)
        self.root.after(250, self.sure_guncelle)
        self.path_entry.focus_set()

    def istatistik(self, parent, baslik, deger, renk):
        card = tk.Frame(parent, bg=self.CARD, highlightbackground="#2b4161", highlightthickness=1)
        card.pack(side="left", fill="x", expand=True, padx=(0, 8))
        tk.Label(card, text=baslik, bg=self.CARD, fg=self.MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=15, pady=(9, 0))
        value = tk.Label(card, text=deger, bg=self.CARD, fg=renk,
                         font=("Segoe UI", 18, "bold"))
        value.pack(anchor="w", padx=15, pady=(0, 8))
        return value

    def baslik_ciz(self, _event=None):
        self.header.delete("all")
        width = self.header.winfo_width()
        title_font = tkfont.Font(family="Segoe UI", size=35, weight="bold")
        title = "ENESWORKS"
        x = (width - title_font.measure(title)) / 2
        self.header_items = []
        for harf in title:
            letter_width = title_font.measure(harf)
            item = self.header.create_text(x + letter_width / 2, 43, text=harf,
                                           font=title_font, fill=self.CYAN)
            self.header_items.append(item)
            x += letter_width
        self.header.create_text(width / 2, 91, text="P R O X Y   C H E C K E R",
                                font=("Segoe UI", 12, "bold"), fill=self.TEXT)
        self.header.create_text(width / 2, 116,
                                text="TXT DOSYASI  /  300 EŞZAMANLI BAĞLANTI  /  CANLI SONUÇ",
                                font=("Segoe UI", 9), fill=self.MUTED)
        self.header_line = []
        for i in range(60):
            x0 = width * i / 60
            self.header_line.append(self.header.create_rectangle(
                x0, 139, width * (i + 1) / 60 + 1, 142, outline="", fill=self.CYAN
            ))

    def renkleri_canlandir(self):
        faz = (time.monotonic() * 0.12) % 1
        for i, item in enumerate(self.header_items):
            self.header.itemconfigure(item, fill=self.rgb((faz + i / 13) % 1))
        for i, item in enumerate(self.header_line):
            self.header.itemconfigure(item, fill=self.rgb((faz + i / 90) % 1))
        self.root.after(70, self.renkleri_canlandir)

    @staticmethod
    def rgb(hue):
        r, g, b = colorsys.hsv_to_rgb(hue, 0.72, 1.0)
        return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"

    def dosya_sec(self):
        yol = filedialog.askopenfilename(parent=self.root, title="Proxy TXT dosyasını seçin",
                                         initialdir=Path.home(), filetypes=[("TXT dosyaları", "*.txt")])
        if yol:
            self.path_var.set(yol)

    def baslat(self):
        if self.busy:
            return
        giris = self.path_var.get().strip()
        if not giris:
            self.status_var.set("Önce TXT dosyasının adını veya yolunu yazın.")
            return
        self.busy = True
        self.stop_event.clear()
        self.output_path = None
        self.output_btn.configure(state="disabled")
        self.start_btn.configure(state="disabled")
        self.dosya_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.scanned_value.configure(text="0 / 0")
        self.live_value.configure(text="0")
        self.time_value.configure(text="00:00")
        self.progress.delete("fill")
        for item in self.table.get_children():
            self.table.delete(item)
        self.status_var.set("Dosya aranıyor...")
        threading.Thread(target=self.ara_isci, args=(giris,), daemon=True).start()

    def ara_isci(self, giris):
        try:
            self.events.put(("dosyalar", dosya_ara(giris)))
        except Exception as hata:
            self.events.put(("hata", f"Dosya aranamadı: {hata}"))

    def dosya_secim_penceresi(self, dosyalar):
        pencere = tk.Toplevel(self.root)
        pencere.title("Dosya seçimi | ENESWORKS")
        pencere.geometry("680x310")
        pencere.configure(bg=self.BG)
        pencere.transient(self.root)
        pencere.grab_set()
        tk.Label(pencere, text="Aynı adda birden fazla TXT bulundu. Birini seçin:",
                 bg=self.BG, fg=self.TEXT, font=("Segoe UI", 11, "bold")).pack(
                     anchor="w", padx=18, pady=(16, 8))
        liste = tk.Listbox(pencere, bg=self.CARD, fg=self.TEXT, selectbackground="#6846ce",
                            selectforeground="white", relief="flat", font=("Segoe UI", 10))
        liste.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        for dosya in dosyalar:
            liste.insert("end", str(dosya))
        liste.selection_set(0)

        def sec():
            secili = liste.curselection()
            if secili:
                dosya = dosyalar[secili[0]]
                pencere.destroy()
                self.path_var.set(str(dosya))
                self.tarama_baslat(dosya)

        def iptal():
            pencere.destroy()
            self.bosa_al()
            self.status_var.set("Dosya seçimi iptal edildi.")

        tk.Button(pencere, text="BU DOSYAYI KULLAN", command=sec, bg="#6846ce",
                  fg="white", relief="flat", font=("Segoe UI", 9, "bold"),
                  padx=16, pady=8).pack(pady=(0, 15))
        liste.bind("<Double-Button-1>", lambda _event: sec())
        pencere.protocol("WM_DELETE_WINDOW", iptal)

    def tarama_baslat(self, dosya):
        self.started = time.monotonic()
        self.status_var.set(f"Okunuyor: {dosya}")
        threading.Thread(target=self.tarama_isci, args=(dosya,), daemon=True).start()

    def tarama_isci(self, dosya):
        try:
            proxyler = listeyi_oku(dosya)
            if not proxyler:
                self.events.put(("hata", "Dosyada geçerli proxy bulunamadı veya dosya okunamadı."))
                return
            self.events.put(("basladi", len(proxyler), str(dosya)))
            sonuclar = asyncio.run(hepsini_test_et(
                proxyler, on_progress=self.ilerleme_bildir, stop_event=self.stop_event
            ))
            hedef = sonuclari_kaydet(sonuclar, masaustu_yolu()) if sonuclar else None
            self.events.put(("bitti", len(sonuclar), hedef, self.stop_event.is_set()))
        except Exception as hata:
            self.events.put(("hata", f"Tarama tamamlanamadı: {hata}"))

    def ilerleme_bildir(self, tamamlanan, toplam, canli, sonuc):
        self.events.put(("ilerleme", tamamlanan, toplam, canli, sonuc))

    def olaylari_isle(self):
        son_ilerleme = None
        try:
            while True:
                olay = self.events.get_nowait()
                tur = olay[0]
                if tur == "dosyalar":
                    dosyalar = olay[1]
                    if not dosyalar:
                        self.bosa_al()
                        self.status_var.set("TXT dosyası bulunamadı. Tam yolu deneyin veya DOSYA SEÇ'e basın.")
                    elif len(dosyalar) == 1:
                        self.path_var.set(str(dosyalar[0]))
                        self.tarama_baslat(dosyalar[0])
                    else:
                        self.dosya_secim_penceresi(dosyalar)
                elif tur == "basladi":
                    self.scanned_value.configure(text=f"0 / {olay[1]}")
                    self.status_var.set(f"Taranıyor: {olay[2]}")
                elif tur == "ilerleme":
                    son_ilerleme = olay
                    sonuc = olay[4]
                    if sonuc:
                        self.table.insert("", "end", values=(
                            f"{sonuc['host']}:{sonuc['port']}", sonuc["tip"],
                            f"{sonuc['gecikme']} ms",
                        ))
                elif tur == "bitti":
                    if son_ilerleme:
                        self.ilerleme_goster(*son_ilerleme[1:4])
                    self.bosa_al()
                    sayi, hedef, durduruldu = olay[1:]
                    if hedef:
                        self.output_path = hedef
                        self.output_btn.configure(state="normal")
                        self.status_var.set(
                            f"{'Durduruldu' if durduruldu else 'Tamamlandı'} · {sayi} çalışan proxy kaydedildi: {hedef}"
                        )
                    else:
                        self.status_var.set(
                            "Tarama durduruldu; çalışan proxy bulunmadı." if durduruldu
                            else "Tarama tamamlandı; çalışan proxy bulunmadı."
                        )
                elif tur == "hata":
                    self.bosa_al()
                    self.status_var.set(olay[1])
        except queue.Empty:
            pass
        if son_ilerleme:
            self.ilerleme_goster(*son_ilerleme[1:4])
        self.root.after(80, self.olaylari_isle)

    def ilerleme_goster(self, tamamlanan, toplam, canli):
        self.scanned_value.configure(text=f"{tamamlanan} / {toplam}")
        self.live_value.configure(text=str(canli))
        self.progress.delete("fill")
        if toplam:
            width = self.progress.winfo_width() * tamamlanan / toplam
            for i in range(40):
                x0 = width * i / 40
                self.progress.create_rectangle(x0, 0, width * (i + 1) / 40 + 1, 12,
                                               fill=self.rgb((0.53 + i / 100) % 1),
                                               outline="", tags="fill")

    def sure_guncelle(self):
        if self.busy and self.started:
            sure = int(time.monotonic() - self.started)
            self.time_value.configure(text=f"{sure // 60:02d}:{sure % 60:02d}")
        self.root.after(250, self.sure_guncelle)

    def durdur(self):
        if self.busy:
            self.stop_event.set()
            self.stop_btn.configure(state="disabled")
            self.status_var.set("Durduruluyor; tamamlanan sonuçlar kaydedilecek...")

    def bosa_al(self):
        self.busy = False
        self.started = None
        self.start_btn.configure(state="normal")
        self.dosya_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def sonucu_ac(self):
        if self.output_path and self.output_path.is_file():
            try:
                if platform.system() == "Windows":
                    os.startfile(self.output_path)
                else:
                    import subprocess
                    komut = "open" if platform.system() == "Darwin" else "xdg-open"
                    subprocess.Popen([komut, str(self.output_path)])
            except OSError as hata:
                self.status_var.set(f"Sonuç dosyası açılamadı: {hata}")

    def kapat(self):
        self.stop_event.set()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Proxy listesindeki çalışan adresleri bulur.")
    parser.add_argument("--file", "-f", type=Path, help="Proxy listesinin TXT dosyası")
    parser.add_argument("--cli", action="store_true", help="Pencere yerine komut satırı kullan")
    args = parser.parse_args()

    if not args.file and not args.cli and tk is not None:
        try:
            ProxyPanel().run()
            return
        except tk.TclError:
            pass

    baslik_goster()

    dosya = args.file if args.file else dosya_bul()
    if dosya is None:
        return
    if not dosya.is_file():
        yaz(f"Dosya bulunamadı: {dosya}", "bold red")
        return

    proxyler = listeyi_oku(dosya)
    if not proxyler:
        yaz("Dosyada geçerli proxy bulunamadı.", "bold red")
        return

    yaz(f"{len(proxyler)} proxy kontrol edilecek  |  {ESZAMANLILIK} eşzamanlı  |  Durdur: Ctrl+C", "#91a5be")
    try:
        sonuclar = asyncio.run(hepsini_test_et(proxyler))
    except KeyboardInterrupt:
        yaz("\nKontrol kullanıcı tarafından durduruldu.", "bold yellow")
        return

    if sonuclar:
        try:
            hedef = sonuclari_kaydet(sonuclar, masaustu_yolu())
        except OSError as hata:
            yaz(f"Sonuç dosyası kaydedilemedi: {hata}", "bold red")
            return
        sonuc_goster(sonuclar, hedef)
    else:
        yaz("Çalışan proxy bulunamadı.", "bold yellow")


if __name__ == "__main__":
    main()
