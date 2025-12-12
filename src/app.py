import webview
import time
import threading
import math
import os
import random
import sys
import json
from datetime import datetime

MAPS_DIR = "maps"
windows = { "main": None, "sim": None }

# --- CHECK DEPENDENCIES ---
def check_dependencies():
    try: import PyQt5; import PyQt5.QtWebEngineWidgets; import qtpy
    except ImportError: sys.exit(1)
check_dependencies()

# --- MOTORE MAPPE ---
class MapGenerator:
    @staticmethod
    def create_turbo_map(base, peak):
        d = bytearray()
        for y in range(16):
            for x in range(16):
                val = int(base + (peak - base) * (y/15.0) * math.sin((x/15.0)*math.pi))
                d.append(min(255, int(val/10)))
        return d

# --- EDITOR ---
class MapEditor:
    def __init__(self):
        self.buffer = bytearray(); self.original_buffer = bytearray(); self.is_loaded = False
        self.filename = ""; self.current_metadata = None; self.active_maps = {} 

    def load_dummy(self, car_specs):
        size = 1024 * 1024; self.buffer = bytearray([0xFF] * size)
        self.active_maps = car_specs.get('maps', {})
        if "Turbo" in self.active_maps:
            a = self.active_maps["Turbo"]["address"]
            p = 2400 if "TDI" in car_specs['name'] else 2100
            for i, b in enumerate(MapGenerator.create_turbo_map(1000, p)): self.buffer[a+i] = b
        for i in range(0, 0x2000): 
            if i%16<8: self.buffer[i] = random.randint(0,255)
        self.original_buffer = self.buffer.copy(); self.is_loaded = True; self.filename = f"{car_specs.get('name','unk')}_read.bin"
        return True

    def load_from_bytes(self, d, f, m=None):
        self.buffer = d.copy(); self.original_buffer = d.copy()
        self.is_loaded = True; self.filename = f; self.current_metadata = m; self.active_maps = m.get("xdf_data", {}) if m else {}

    def load_from_disk(self, p):
        try:
            with open(p, "rb") as f: d = bytearray(f.read())
            self.load_from_bytes(d, os.path.basename(p))
            return True
        except: return False

    def load_xdf(self, path):
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(path); root = tree.getroot(); found = {}
            for t in root.findall("XDFTABLE"):
                title = t.find("title").text
                for e in t.iter():
                    if 'mmedaddress' in e.attrib:
                        val = e.attrib['mmedaddress']
                        addr = int(val, 16) if '0x' in val.lower() else int(val)
                        found[title] = {"address": addr}
                        break
            if found: self.active_maps = found; return True, len(found)
        except: pass
        return False, 0

    def apply_stage(self, s):
        if not self.is_loaded: return False, "No File"
        tm = next((v for k,v in self.active_maps.items() if "Turbo" in k), None)
        em = next((v for k,v in self.active_maps.items() if "EGR" in k), None)
        c = 0
        if s == "stage1":
            if not tm: return False, "Serve XDF con Turbo!"
            a = tm["address"]
            for i in range(256):
                if self.buffer[a+i] > 120:
                    self.buffer[a+i] = min(255, int(self.buffer[a+i]*1.15)); c+=1
            return True, f"Stage 1: +15% ({c} celle)"
        elif s == "egroff":
            if not em: return False, "Serve XDF con EGR!"
            a = em["address"]
            for i in range(16): self.buffer[a+i] = 0x00
            return True, "EGR Chiusa"
        elif s == "popbang":
            for i in range(32): self.buffer[0x9000+i] = 0x00
            return True, "Pop & Bang attivato"
        elif s == "restore":
            self.buffer = self.original_buffer.copy(); return True, "Ripristinato"
        return False, "Stage sconosciuto"

    def get_hex_chunk(self, o, s=256):
        if not self.is_loaded: return [], []
        e = min(o + s, len(self.buffer))
        c = list(self.buffer[o:e]); og = list(self.original_buffer[o:e])
        if len(c)<s: c+=[0]*(s-len(c)); og+=[0]*(s-len(og))
        return c, og

    def write_byte(self, o, v):
        if self.is_loaded and 0 <= o < len(self.buffer): self.buffer[o] = v; return True
        return False

# --- ARCHIVIO ---
class MapLibrary:
    def __init__(self):
        if not os.path.exists(MAPS_DIR): os.makedirs(MAPS_DIR, exist_ok=True)
    def save_map(self, n, d, i, m=False):
        fn = f"{''.join(c for c in n if c.isalnum() or c in ' _-').strip()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
        try:
            with open(os.path.join(MAPS_DIR, fn), "wb") as f: f.write(d)
            meta = {"original_filename":fn, "car_name":i['name'], "ecu_hw":i['ecu_hw'], "type":"MOD" if m else "ORI"}
            with open(os.path.join(MAPS_DIR, fn+".json"), "w") as f: json.dump(meta, f, indent=4)
            return True, fn
        except Exception as e: return False, str(e)
    def get_all_maps(self):
        l=[]
        if os.path.exists(MAPS_DIR):
            for f in os.listdir(MAPS_DIR):
                if f.endswith(".bin"):
                    try: 
                        with open(os.path.join(MAPS_DIR, f+".json")) as j: d=json.load(j); l.append({"filename":f, "name":d.get("car_name","?"), "ecu":d.get("ecu_hw","?"), "type":d.get("type","?")})
                    except: pass
        return l
    def load_map_data(self, f):
        try:
            with open(os.path.join(MAPS_DIR, f), "rb") as fh: d=bytearray(fh.read())
            with open(os.path.join(MAPS_DIR, f+".json")) as j: m=json.load(j)
            return d, m
        except: return None, None
    def delete_map(self, f):
        try: 
            os.remove(os.path.join(MAPS_DIR, f)); os.remove(os.path.join(MAPS_DIR, f+".json"))
            x = os.path.join(MAPS_DIR, f.replace(".bin", "_ORI") + ".xdf")
            if os.path.exists(x): os.remove(x)
            return True
        except: return False

# --- AUTO & FISICA ---
class CarDatabase:
    def __init__(self):
        self.cars = {
            "audi_a3": { "name": "Audi A3 2.0 TDI", "ecu_hw": "EDC17C64", "ecu_sw": "03L906", "mass": 1350, "hp": 150, "torque": 340, "max_rpm": 5000, "ratios": {1: 3.46, 2: 2.05, 3: 1.3, 4: 0.9, 5: 0.91, 6: 0.76, 'R': 3.99}, "final_drive": 3.4, "maps": {"Turbo": {"address": 0x4E20}, "EGR": {"address": 0x1C00}} },
            "golf_gti": { "name": "VW Golf VII GTI", "ecu_hw": "Simos 18", "ecu_sw": "5G0906", "mass": 1400, "hp": 230, "torque": 350, "max_rpm": 7000, "ratios": {1: 2.92, 2: 1.79, 3: 1.14, 4: 0.78, 5: 0.8, 6: 0.64, 'R': 3.26}, "final_drive": 4.7, "maps": {"Turbo": {"address": 0x8200}, "EGR": {"address": 0x2A00}} },
            "alfa_giulia": { "name": "Alfa Giulia QV", "ecu_hw": "ME17.3.5", "ecu_sw": "0261S1", "mass": 1620, "hp": 510, "torque": 600, "max_rpm": 7400, "ratios": {1: 5.0, 2: 3.2, 3: 2.14, 4: 1.72, 5: 1.31, 6: 1.0, 7: 0.82, 8: 0.64, 'R': 3.4}, "final_drive": 3.09, "maps": {"Turbo": {"address": 0x6000}, "EGR": {"address": 0x1500}} }
        }
        self.current_car_id = "golf_gti"
    def get_current_specs(self): return self.cars.get(self.current_car_id, self.cars["golf_gti"])
    def select_car(self, i): self.current_car_id=i; return self.get_current_specs()

class PhysicsEngine:
    def __init__(self, db): self.db=db; self.lock=threading.Lock(); self.running=True; self.reset_physics(); threading.Thread(target=self._loop, daemon=True).start()
    def reset_physics(self):
        s=self.db.get_current_specs()
        with self.lock: self.throttle=0.0; self.brake=0.0; self.gear_selector='P'; self.engine_on=False; self.velocity_ms=0.0; self.rpm=0.0; self.current_gear=1; self.temp=25.0; self.volt=12.4; self.MASS=s['mass']; self.TORQUE_MAX=s['torque']; self.MAX_RPM=s['max_rpm']; self.GEAR_RATIOS=s['ratios']; self.FINAL_DRIVE=s['final_drive']; self.IDLE_RPM=800
    def load_new_car(self, cid): self.db.select_car(cid); self.reset_physics()
    def _loop(self):
        lt=time.time()
        while self.running:
            ct=time.time(); dt=min(0.1, ct-lt); lt=ct
            with self.lock:
                if self.engine_on: self.volt=13.8+random.random()*0.2; self.temp=min(90, self.temp+0.05)
                else: self.volt=12.4
                if not self.engine_on: self.rpm=max(0, self.rpm-1500*dt); self.velocity_ms*=0.99
                else:
                    if self.gear_selector=='D':
                        f=(self.throttle*self.TORQUE_MAX*4.0)/0.3; 
                        if self.throttle<0.05 and self.rpm<1100: f=max(f, 300.0)
                        a=(f - (0.5*1.2*2.2*0.3*self.velocity_ms**2) - (self.brake*15000))/self.MASS
                        self.velocity_ms=max(0, self.velocity_ms+a*dt)
                        self.rpm=max(self.IDLE_RPM+(self.throttle*2000), (self.velocity_ms/0.3)*4.0*9.55)
                    elif self.gear_selector in ['P','N']: self.rpm+=(self.IDLE_RPM+(self.throttle*(self.MAX_RPM-500))-self.rpm)*5*dt; self.velocity_ms*=0.98
                self.rpm=min(self.rpm, self.MAX_RPM)
            time.sleep(0.02)
    def get_state(self):
        with self.lock: return {"rpm":int(self.rpm), "speed":int(self.velocity_ms*3.6), "gear":self.gear_selector, "engine_on":self.engine_on, "temp":int(self.temp), "volt":round(self.volt,1), "throttle":int(self.throttle*100), "car":self.db.get_current_specs()['name']}

class FlashManager:
    def __init__(self, db, lib): self.db=db; self.lib=lib; self.p=0; self.st="Idle"; self.work=False; self.log=[]
    def lg(self, m): self.log.append(f"[{time.strftime('%H:%M:%S')}] {m}")
    def run_read(self, me):
        if self.work: return
        self.work=True; self.p=0; self.log=[]
        threading.Thread(target=self._sim_read, args=(me,)).start()
    def run_write(self, me):
        if self.work: return
        self.work=True; self.p=0; self.log=[]
        threading.Thread(target=self._sim_write, args=(me,)).start()
    def _sim_read(self, me):
        try:
            c=self.db.get_current_specs(); self.lg(f"Lettura {c['name']}..."); time.sleep(1)
            for i in range(101): self.p=i; self.st=f"Reading {i}%"; time.sleep(0.015)
            me.load_dummy(c)
            ok, f = self.lib.save_map(c['name']+"_ORI", me.buffer, c, False)
            import xml.etree.ElementTree as ET
            root = ET.Element("XDFFORMAT", version="1.60")
            for n,d in c['maps'].items():
                t = ET.SubElement(root, "XDFTABLE", uniqueid=f"0x{random.randint(0,999):X}", flags="0x1")
                ET.SubElement(t, "title").text = n
                ET.SubElement(ET.SubElement(t, "XDFAXIS", id="z", uniqueid="0x0"), "EMBEDDEDDATA", mmedaddress=f"0x{d['address']:X}", mmedelementsizebits="8")
            try: ET.ElementTree(root).write(os.path.join(MAPS_DIR, f.replace(".bin","_ORI")+".xdf"), encoding="UTF-8", xml_declaration=True)
            except: pass
            self.lg(f"Salvato: {f}"); self.st="Finito"
        except Exception as e: self.lg(str(e)); self.st="Errore"
        finally: self.work=False
    def _sim_write(self, me):
        try:
            if not me.is_loaded: self.lg("No File"); return
            self.lg("Checksum..."); time.sleep(1)
            for i in range(101): self.p=i; self.st=f"Writing {i}%"; time.sleep(0.02)
            self.st="Finito"; self.lg("Flash OK.")
        except Exception as e: self.lg(str(e)); self.st="Errore"
        finally: self.work=False

class Api:
    def __init__(self):
        self.db=CarDatabase(); self.lib=MapLibrary(); self.phys=PhysicsEngine(self.db); self.fl=FlashManager(self.db, self.lib); self.ed=MapEditor(); self.mode='sim'; self.conn=None
    
    # --- HERE IS THE FIX: Using the correct name expected by simulator.html ---
    def get_available_cars(self): 
        return self.db.cars

    def sel_sim_car(self, id): return self.select_sim_car(id) # Alias for robustness
    def select_sim_car(self, id): self.phys.load_new_car(id); return self.db.get_current_specs()
    
    def sim_control(self, t,b,s,i): 
        try: 
            if t is not None: self.phys.throttle=float(t)
            if b is not None: self.phys.brake=float(b)
        except: pass
        if i is not None: self.phys.engine_on=bool(i)
        if s: self.phys.gear_selector=str(s)
    
    def open_sim(self): 
        if windows['sim']: 
            try: windows['sim'].show(); return
            except: windows['sim']=None
        windows['sim'] = webview.create_window('Garage', 'simulator.html', js_api=self, width=500, height=750, resizable=True)
    def set_mode(self, m): 
        self.mode=m
        if m=='sim': threading.Timer(0.2, self.open_sim).start()
    
    def get_data(self): return self.phys.get_state()
    def get_ecu_info(self): return self.db.get_current_specs()
    def read_ecu(self): self.fl.run_read(self.ed); return {"msg":"OK"}
    def write_ecu(self): self.fl.run_write(self.ed); return {"msg":"OK"}
    def get_status(self): return {"p":self.fl.p, "s":self.fl.st, "l":self.fl.log, "w":self.fl.work, "f":self.ed.is_loaded, "fn":self.ed.filename}
    def get_hex(self, o): return self.ed.get_hex_chunk(int(o))
    def upd_hex(self, o, v): return self.ed.write_byte(int(o), int(v, 16))
    def app_wiz(self, s): ok, m = self.ed.apply_stage(s); return {"status":"success" if ok else "error", "msg":m}
    def get_maps(self): return self.lib.get_all_maps()
    def load_map(self, f): d,m=self.lib.load_map_data(f); self.ed.load_from_bytes(d,f,m) if d else None; return {"status":"success", "msg":"OK"}
    def save_map(self, s):
        if not self.ed.is_loaded: return {"status":"error", "msg":"No Data"}
        c=self.db.get_current_specs(); m=self.ed.current_metadata if self.ed.current_metadata else c
        if not 'maps' in m and 'maps' in c: m['maps']=c['maps']
        ok, f = self.lib.save_map(f"{m['name']}_{s}", self.ed.buffer, m, True)
        return {"status":"success", "msg":f"Salvato {f}"}
    def del_map(self, f): self.lib.delete_map(f)
    def get_def_maps(self): return self.ed.active_maps
    def get_sim_state(self): return self.phys.get_state()
    def load_xdf_file(self):
        try:
            r=webview.windows[0].create_file_dialog(webview.OPEN_DIALOG, file_types=('XDF (*.xdf)', 'All (*.*)'))
            if r and len(r)>0: ok,c=self.ed.load_xdf(r[0]); return {"status":"success", "msg":f"XDF: {c} maps"} if ok else {"status":"error"}
        except: pass
        return {"status":"error"}
    def pick_file(self): 
        try: 
            r=webview.windows[0].create_file_dialog(webview.OPEN_DIALOG, file_types=('Bin (*.bin)', 'All (*.*)'))
            if r and len(r)>0: 
                if self.ed.load_from_disk(r[0]): return os.path.basename(r[0])
        except: pass
        return None
    def get_hex_view_with_graph(self, offset):
        c, o = self.ed.get_hex_chunk(int(offset))
        return {"current": c, "original": o}
    def get_ports(self): 
        if self.mode == 'sim': return ["SIMULATORE"]
        else: 
            import serial.tools.list_ports
            return [p.device for p in serial.tools.list_ports.comports()]
    def connect_ecu(self, p): return {"status":"success"}
    def disconnect(self): return {"status":"success"}

if __name__ == '__main__':
    api = Api()
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    windows['main'] = webview.create_window('ECU Tuner Suite v6', 'index.html', js_api=api, width=1280, height=900, background_color='#0a0a0a')
    webview.start(debug=False, gui='qt')