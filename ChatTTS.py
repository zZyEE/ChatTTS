# ==========================================
# 程序名稱: ChatTTS
# 開發者: ZyEE(Gemini)
# 協助開發: Google Gemini AI
# 版本: V1.20
# 功能: Twitch 語音助手 (Edge-TTS)
# 版權所有，轉載請註明出處
# ==========================================
import tkinter as tk
from tkinter import ttk
import edge_tts
import asyncio
import random
import threading
import os
import pygame
import irc.bot
import json
import re
import queue

CONFIG_FILE = "config.json"
DICT_FILE = "dict.txt"

class ChatSpeechIRC(irc.bot.SingleServerIRCBot):
    def __init__(self, channel, nickname, callback):
        server = "irc.chat.twitch.tv"
        port = 6667
        super().__init__([(server, port)], nickname, nickname)
        self.target_channel = f"#{channel}"
        self.callback = callback

    def on_welcome(self, c, e):
        c.join(self.target_channel)

    def on_pubmsg(self, c, e):
        source = e.source.split('!')
        user_name = source[0] if source else "Unknown"
        msg_content = e.arguments[0] if isinstance(e.arguments, list) else str(e.arguments)
        self.callback(user_name, msg_content)

    def disconnect_bot(self):
        if self.connection.is_connected():
            self.connection.disconnect("User disconnected")
        self.die()

class ChatSpeechApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ChatTTS byZyEE")
        self.root.geometry("550x780")

        self.user_voice_map = {}
        self.last_assigned_voice = None
        self.bot = None
        self.all_voices = []
        self.replace_dict = {}
        self.speak_queue = queue.Queue()
        self.is_playing = True
        
        pygame.mixer.init()
        self.cleanup_temp_files()
        self.config = self.load_config()
        self.setup_ui()
        self.load_dict()
        
        threading.Thread(target=self.voice_worker, daemon=True).start()
        threading.Thread(target=self.fetch_voices, daemon=True).start()

    def cleanup_temp_files(self):
        for f in os.listdir("."):
            if f.startswith("temp_") and f.endswith(".mp3"):
                try: os.remove(f)
                except: pass

    def load_dict(self):
        self.replace_dict = {}
        if not os.path.exists(DICT_FILE):
            with open(DICT_FILE, 'w', encoding='utf-8') as f:
                f.write("[TWITCH_LINK],圖奇連結\n[YOUTUBE_LINK],油兔連結\n[OTHER_LINK],發了個連結\n")
        try:
            with open(DICT_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if ',' in line:
                        parts = line.strip().split(',', 1)
                        old = parts[0].strip()
                        new = parts[1].strip() if len(parts) > 1 else ""
                        if old: self.replace_dict[old] = new
            self.log("系統：字典規則已刷新。")
        except: pass

    def clean_text(self, text):
        text = str(text)
        
        # 1. 將連結轉化為「佔位標籤」，不在此處寫死朗讀內容
        # 處理 Twitch (包含純域名)
        twitch_pat = r'https?://(www\.)?twitch\.tv(/\S*)?'
        text = re.sub(twitch_pat, ' [TWITCH_LINK] ', text, flags=re.I)
        
        # 處理 YouTube
        yt_pat = r'https?://(www\.)?(youtube\.com|youtu\.be)(/\S*)?'
        text = re.sub(yt_pat, ' [YOUTUBE_LINK] ', text, flags=re.I)

        # 處理其餘通用連結
        other_url_pat = r'https?://\S+'
        text = re.sub(other_url_pat, ' [OTHER_LINK] ', text, flags=re.I)
        
        # 2. 套用字典替換 (此時 [TWITCH_LINK] 等標籤會被替換成你在 dict.txt 定義的文字)
        for old, new in self.replace_dict.items():
            text = text.replace(old, new)
            
        return text.strip()[:100]

    def load_config(self):
        default_cfg = {"channel": "", "voices": ["zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural"], "volume": 100, "speed_norm": 1.0, "speed_fast": 2.5, "auto_mode": False}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    user_cfg = json.load(f)
                    for k, v in default_cfg.items():
                        if k not in user_cfg: user_cfg[k] = v
                    return user_cfg
            except: pass
        return default_cfg

    def save_config(self):
        self.config = {
            "channel": self.channel_entry.get(),
            "voices": [v.get() for v in self.voice_vars],
            "volume": self.vol_var.get(),
            "speed_norm": round(self.speed_norm.get(), 1),
            "speed_fast": round(self.speed_fast.get(), 1),
            "auto_mode": self.auto_var.get()
        }
        with open(CONFIG_FILE, 'w') as f: json.dump(self.config, f)

    def setup_ui(self):
        # 聲音庫設定
        group_voice = ttk.LabelFrame(self.root, text=" 聲音庫設定 ")
        group_voice.pack(padx=10, pady=5, fill="x")
        self.voice_vars, self.voice_combos = [], []
        for i in range(3):
            f = ttk.Frame(group_voice); f.pack(fill="x", padx=5, pady=2)
            ttk.Label(f, text=f"聲音 {i+1}:").pack(side="left")
            var = tk.StringVar(value=self.config["voices"][i])
            cb = ttk.Combobox(f, textvariable=var, state="readonly")
            cb.pack(side="right", fill="x", expand=True, padx=5)
            self.voice_vars.append(var); self.voice_combos.append(cb)

        # Twitch 設定
        group_channel = ttk.LabelFrame(self.root, text=" Twitch 設定 ")
        group_channel.pack(padx=10, pady=5, fill="x")
        f1 = ttk.Frame(group_channel); f1.pack(fill="x", padx=5, pady=5)
        self.channel_entry = ttk.Entry(f1); self.channel_entry.insert(0, self.config["channel"])
        self.channel_entry.pack(side="left", expand=True, fill="x", padx=5)
        self.start_btn = ttk.Button(f1, text="連接", command=self.toggle_monitoring); self.start_btn.pack(side="left", padx=2)
        self.stop_btn = ttk.Button(f1, text="斷開", command=self.stop_monitoring, state="disabled"); self.stop_btn.pack(side="left", padx=2)

        # 語音與 Auto 控制
        group_ctrl = ttk.LabelFrame(self.root, text=" 語音與 Auto 模式控制 ")
        group_ctrl.pack(padx=10, pady=5, fill="x")

        left_f = ttk.Frame(group_ctrl); left_f.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        ttk.Label(left_f, text="總音量:").grid(row=0, column=0, sticky="w")
        self.vol_var = tk.IntVar(value=self.config["volume"])
        self.vol_lbl = ttk.Label(left_f, text=f"{self.vol_var.get()}%"); self.vol_lbl.grid(row=0, column=2)
        ttk.Scale(left_f, from_=0, to=100, variable=self.vol_var, command=lambda e: self.vol_lbl.config(text=f"{self.vol_var.get()}%")).grid(row=0, column=1, sticky="ew")

        ttk.Label(left_f, text="固定語速:").grid(row=1, column=0, sticky="w")
        self.speed_norm = tk.DoubleVar(value=self.config["speed_norm"])
        self.norm_lbl = ttk.Label(left_f, text=f"{self.speed_norm.get():.1f}x"); self.norm_lbl.grid(row=1, column=2)
        ttk.Scale(left_f, from_=1.0, to=5.0, variable=self.speed_norm, command=lambda e: self.norm_lbl.config(text=f"{self.speed_norm.get():.1f}x")).grid(row=1, column=1, sticky="ew")

        ttk.Separator(group_ctrl, orient="vertical").pack(side="left", fill="y", padx=10)

        right_f = ttk.Frame(group_ctrl); right_f.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.auto_var = tk.BooleanVar(value=self.config["auto_mode"])
        ttk.Checkbutton(right_f, text="啟動 Auto 加速", variable=self.auto_var, command=self.update_auto_ui).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0,5))
        self.lbl_fast = ttk.Label(right_f, text="加速語速:"); self.lbl_fast.grid(row=1, column=0, sticky="w")
        self.speed_fast = tk.DoubleVar(value=self.config["speed_fast"])
        self.fast_lbl = ttk.Label(right_f, text=f"{self.speed_fast.get():.1f}x"); self.fast_lbl.grid(row=1, column=2)
        self.sc_fast = ttk.Scale(right_f, from_=1.0, to=5.0, variable=self.speed_fast, command=lambda e: self.fast_lbl.config(text=f"{self.speed_fast.get():.1f}x"))
        self.sc_fast.grid(row=1, column=1, sticky="ew")

        self.update_auto_ui()
        
        # 佈局：字典按鈕絕對居中，排隊提示 padx=30
        tool_frame = ttk.Frame(self.root, height=40)
        tool_frame.pack(fill="x", padx=10, pady=5)
        tool_frame.pack_propagate(False)

        self.dict_btn = ttk.Button(tool_frame, text="重新載入字典 (dict.txt)", command=self.load_dict)
        self.dict_btn.place(relx=0.5, rely=0.5, anchor="center")
        
        self.queue_label = ttk.Label(tool_frame, text="目前排隊中: 0 條留言", foreground="blue")
        self.queue_label.pack(side="right", padx=(0, 30), pady=10)

        # 日誌區
        self.log_box = tk.Text(self.root, height=18, state="disabled", bg="#f8f8f8")
        self.log_box.pack(padx=10, pady=5, fill="both", expand=True)

    def update_auto_ui(self):
        state = "normal" if self.auto_var.get() else "disabled"
        self.lbl_fast.config(state=state); self.fast_lbl.config(state=state); self.sc_fast.config(state=state)

    def fetch_voices(self):
        async def get():
            try:
                voices = await edge_tts.list_voices()
                self.all_voices = sorted([v['ShortName'] for v in voices])
                self.root.after(0, self.update_voice_combos)
            except: pass
        asyncio.run(get())

    def update_voice_combos(self):
        for combo in self.voice_combos: combo['values'] = self.all_voices

    def log(self, text):
        self.log_box.config(state="normal"); self.log_box.insert("end", text + "\n"); self.log_box.see("end"); self.log_box.config(state="disabled")

    def toggle_monitoring(self):
        channel = self.channel_entry.get().strip().lower()
        if not channel: return
        self.save_config(); self.log(f"系統：正在連接 #{channel}...")
        nick = f"justinfan{random.randint(1000, 9999)}"
        self.bot = ChatSpeechIRC(channel, nick, self.process_chat)
        threading.Thread(target=self.bot.start, daemon=True).start()
        self.start_btn.config(state="disabled"); self.stop_btn.config(state="normal"); self.channel_entry.config(state="disabled")

    def stop_monitoring(self):
        if self.bot: threading.Thread(target=self.bot.disconnect_bot, daemon=True).start(); self.bot = None
        self.user_voice_map.clear()
        self.log("系統：已斷開連線，語音記憶已清空。")
        self.start_btn.config(state="normal"); self.stop_btn.config(state="disabled"); self.channel_entry.config(state="normal")

    def process_chat(self, user_name, msg):
        clean_msg = self.clean_text(msg)
        self.log(f"[{user_name}]: {msg}")
        if user_name not in self.user_voice_map:
            choices = [v.get() for v in self.voice_vars]
            new_v = random.choice(choices)
            if len(set(choices)) > 1:
                while new_v == self.last_assigned_voice: new_v = random.choice(choices)
            self.user_voice_map[user_name] = new_v
            self.last_assigned_voice = new_v
        self.speak_queue.put((clean_msg, self.user_voice_map[user_name]))
        self.root.after(0, lambda: self.queue_label.config(text=f"目前排隊中: {self.speak_queue.qsize()} 條留言"))

    def voice_worker(self):
        while self.is_playing:
            try:
                text, voice = self.speak_queue.get(timeout=1)
                q_size = self.speak_queue.qsize()
                self.root.after(0, lambda s=q_size: self.queue_label.config(text=f"目前排隊中: {s} 條留言"))
                speed = self.speed_fast.get() if (self.auto_var.get() and q_size >= 5) else self.speed_norm.get()
                rate = f"+{int((speed-1)*100)}%"
                v = self.vol_var.get()
                vol_offset = f"+{v-100}%" if v >= 100 else f"-{100-v}%"
                asyncio.run(self.run_tts_sync(text, voice, rate, vol_offset))
                self.speak_queue.task_done()
            except queue.Empty: continue

    async def run_tts_sync(self, text, voice, rate, volume):
        fname = f"temp_{random.randint(1000,9999)}.mp3"
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
            await comm.save(fname)
            pygame.mixer.music.load(fname)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy(): await asyncio.sleep(0.05)
            pygame.mixer.music.unload()
            if os.path.exists(fname): os.remove(fname)
        except: pass

if __name__ == "__main__":
    root = tk.Tk(); app = ChatSpeechApp(root); root.mainloop()
