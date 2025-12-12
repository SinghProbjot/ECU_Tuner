import webview
import time
import threading
import math
import os
import random
import sys
import json
import shutil
from datetime import datetime

# --- CONFIGURAZIONE ---
MAPS_DIR = "maps"

# --- CHECK DIPENDENZE ---
def check_dependencies():
    missing = []
    try: import PyQt5
    except ImportError: missing.append("PyQt5")
    try: import PyQt5.QtWebEngineWidgets
    except ImportError: missing.append("PyQtWebEngine")
    try: import qtpy
    except ImportError: missing.append("qtpy")
    if missing:
        print(f"ERRORE: Mancano librerie. Esegui: pip install {' '.join(missing)}")
        sys.exit(1)

check_dependencies()

# --- GESTORE ARCHIVIO MAPPE ---
class MapLibrary:
    def __init__(self):
        if not os.path.exists(MAPS_DIR):
            os.makedirs(MAPS_DIR)

    def save_map(self, name, data, car_info, is_mod=False):
        # Pulisci il nome file
        clean_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{clean_name}_{timestamp}.bin"
        filepath = os.path.join(MAPS_DIR, filename)
        
        # Salva il binario
        try:
            with open(filepath, "wb") as f:
                f.write(data)
            
            # Salva i metadati (per il controllo sicurezza)
            meta = {
                "original_filename": filename,
                "car_name": car_info['name'],
                "ecu_hw": car_info['ecu_hw'],
                "ecu_sw": car_info['ecu_sw'],
                "type": "MOD" if is_mod else "ORI",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "size": len(data)
            }
            with open(filepath + ".json", "w") as f:
                json.dump(meta, f, indent=4)
                
            return True, filename
        except Exception as e:
            return False, str(e)

    def get_all_maps(self):
        maps = []
        if not os.path.exists(MAPS_DIR): return []
        
        for f in os.listdir(MAPS_DIR):
            if f.endswith(".bin"):
                meta_path = os.path.join(MAPS_DIR, f + ".json")
                meta = {}
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r") as jf: meta = json.load(jf)
                    except: pass
                
                maps.append({
                    "filename": f,
                    "name": meta.get("car_name", "Sconosciuto"),
                    "type": meta.get("type", "UNK"),
                    "ecu": meta.get("ecu_hw", "---"),
                    "date": meta.get("date", "")
                })
        return maps

    def load_map_data(self, filename):
        path = os.path.join(MAPS_DIR, filename)
        meta_path = path + ".json"
        data = None
        meta = None
        
        if os.path.exists(path):
            with open(path, "rb") as f: data = bytearray(f.read())
        
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f: meta = json.load(f)
            
        return data, meta

    def delete_map(self, filename):
        try:
            path = os.path.join(MAPS_DIR, filename)
            if os.path.exists(path): os.remove(path)
            if os.path.exists(path + ".json"): os.remove(path + ".json")
            return True
        except: return False

# --- GESTORE MAPPE IN RAM (EDITOR) ---
class MapEditor:
    def __init__(self):
        self.buffer = bytearray()
        self.is_loaded = False
        self.current_filename = ""
        self.current_metadata = None # Dati dell'auto associata al file caricato

    def load_dummy(self):
        self.buffer = bytearray(random.getrandbits(8) for _ in range(1024 * 512))
        self.is_loaded = True
        self.current_filename = "virtual_read.bin"
        self.current_metadata = None # Reset metadata su nuovo file dummy

    def load_from_bytes(self, data, filename, meta=None):
        self.buffer = data.copy()
        self.is_loaded = True
        self.current_filename = filename
        self.current_metadata = meta

    def apply_stage(self, stage_type):
        if not self.is_loaded: return False
        if stage_type == "stage1":
            for i in range(0x4000, 0x4100): 
                if self.buffer[i] < 240: self.buffer[i] += 10
        elif stage_type == "popbang":
            for i in range(0x8000, 0x8050): self.buffer[i] = 0xFF
        elif stage_type == "egroff":
            for i in range(0x1000, 0x1020): self.buffer[i] = 0x00
        return True

    def get_hex_chunk(self, offset, size=256):
        if not self.is_loaded: return [0] * size
        end = min(offset + size, len(self.buffer))
        chunk = self.buffer[offset:end]
        if len(chunk) < size: chunk += bytearray(size - len(chunk))
        return list(chunk)

    def write_byte(self, offset, val):
        if self.is_loaded and 0 <= offset < len(self.buffer):
            self.buffer[offset] = val
            return True
        return False

# --- DATABASE AUTO ---
class CarDatabase:
    def __init__(self):
        self.cars = {
            "audi_a3": { "name": "Audi A3 2.0 TDI", "ecu_hw": "Bosch EDC17 C46", "ecu_sw": "03L906018", "mass": 1350, "hp": 150, "torque": 340, "max_rpm": 5000, "ratios": {1: 3.46, 2: 2.05, 3: 1.3, 4: 0.90, 5: 0.91, 6: 0.76, 'R': 3.99}, "final_drive": 3.4 },
            "golf_gti": { "name": "VW Golf VII GTI", "ecu_hw": "Bosch EDC17 Simos18", "ecu_sw": "5G0906259", "mass": 1400, "hp": 230, "torque": 350, "max_rpm": 7000, "ratios": {1: 2.92, 2: 1.79, 3: 1.14, 4: 0.78, 5: 0.80, 6: 0.64, 'R': 3.26}, "final_drive": 4.7 },
            "alfa_giulia": { "name": "Alfa Giulia QV", "ecu_hw": "Bosch EDC17 CP79", "ecu_sw": "1037552342", "mass": 1620, "hp": 510, "torque": 600, "max_rpm": 7400, "ratios": {1: 5.0, 2: 3.2, 3: 2.14, 4: 1.72, 5: 1.31, 6: 1.0, 7: 0.82, 8: 0.64, 'R': 3.4}, "final_drive": 3.09 }
        }
        self.current_car_id = "golf_gti"
    def get_current_specs(self): return self.cars.get(self.current_car_id, self.cars["golf_gti"])
    def select_car(self, car_id):
        if car_id in self.cars: self.current_car_id = car_id
        return self.get_current_specs()

# --- MOTORE FISICO ---
class PhysicsEngine:
    def __init__(self, db):
        self.db = db; self.lock = threading.Lock(); self.running = True
        self.reset_physics()
        threading.Thread(target=self._loop, daemon=True).start()

    def reset_physics(self):
        specs = self.db.get_current_specs()
        with self.lock:
            self.throttle = 0.0; self.brake = 0.0; self.gear_selector = 'P'; self.engine_on = False
            self.velocity_ms = 0.0; self.rpm = 0.0; self.current_gear = 1
            self.coolant_temp = 25.0; self.battery_volts = 12.4
            self.MASS = specs['mass']; self.TORQUE_MAX = specs['torque']; self.MAX_RPM = specs['max_rpm']
            self.GEAR_RATIOS = specs['ratios']; self.FINAL_DRIVE = specs['final_drive']; self.IDLE_RPM = 800

    def load_new_car(self, car_id): self.db.select_car(car_id); self.reset_physics()

    def _loop(self):
        last_t = time.time()
        while self.running:
            cur_t = time.time(); dt = cur_t - last_t; last_t = cur_t
            if dt > 0.1: dt = 0.1
            with self.lock:
                if self.engine_on:
                    self.battery_volts = 13.8 + (random.random() * 0.2)
                    if self.coolant_temp < 90: self.coolant_temp += 0.05
                else: self.battery_volts = 12.4
                if not self.engine_on:
                    self.rpm = max(0, self.rpm - 1500*dt); self.velocity_ms *= 0.99
                else:
                    if self.gear_selector == 'D':
                        ratio = self.GEAR_RATIOS.get(self.current_gear, 1.0) * self.FINAL_DRIVE
                        if self.rpm > (self.MAX_RPM - 1000) and self.current_gear < 6: self.current_gear += 1
                        if self.rpm < 1500 and self.current_gear > 1: self.current_gear -= 1
                        force = (self.throttle * self.TORQUE_MAX * ratio) / 0.3
                        if self.throttle < 0.05 and self.rpm < (self.IDLE_RPM + 300): force = max(force, (80.0 * ratio) / 0.3)
                        drag = 0.5 * 1.2 * 2.2 * 0.3 * (self.velocity_ms**2)
                        accel = (force - drag - (self.brake * 15000)) / self.MASS
                        self.velocity_ms += accel * dt
                        if self.velocity_ms < 0: self.velocity_ms = 0
                        mech_rpm = (self.velocity_ms / 0.3) * ratio * 9.55
                        self.rpm = max(self.IDLE_RPM + (self.throttle*2000), mech_rpm)
                    elif self.gear_selector in ['P', 'N']:
                        target = self.IDLE_RPM + (self.throttle * (self.MAX_RPM - 500))
                        self.rpm += (target - self.rpm) * 5 * dt
                        self.velocity_ms *= 0.98
                        if self.gear_selector == 'P': self.velocity_ms = 0
                self.rpm = min(self.rpm, self.MAX_RPM)
            time.sleep(0.02)

    def get_state(self):
        with self.lock: return {
            "rpm": int(self.rpm), "speed": int(self.velocity_ms*3.6), 
            "gear": self.gear_selector, "engine_on": self.engine_on,
            "temp": int(self.coolant_temp), "volt": round(self.battery_volts, 1),
            "throttle": int(self.throttle*100), "car": self.db.get_current_specs()['name']
        }

# --- FLASHING MANAGER ---
class FlashManager:
    def __init__(self, db, lib):
        self.db = db; self.lib = lib
        self.progress = 0; self.status = "Idle"; self.is_working = False; self.log_msg = []
    
    def log(self, m): self.log_msg.append(f"[{time.strftime('%H:%M:%S')}] {m}")

    def start_read(self, map_editor):
        self.is_working = True; self.progress = 0; self.log_msg = []
        threading.Thread(target=self._sim_read, args=(map_editor,)).start()

    def start_write(self, map_editor):
        self.is_working = True; self.progress = 0; self.log_msg = []
        threading.Thread(target=self._sim_write, args=(map_editor,)).start()

    def _sim_read(self, map_editor):
        car = self.db.get_current_specs()
        self.log(f"Protocollo KWP2000: {car['ecu_hw']}")
        time.sleep(1)
        self.log(f"Seed/Key Security Access... OK")
        time.sleep(0.5)
        for i in range(101):
            self.progress = i; self.status = f"Lettura {i}%"; time.sleep(0.02)
        
        # Genera il file e SALVALO NELLA LIBRERIA
        map_editor.load_dummy_file()
        ok, fname = self.lib.save_map(car['name'] + "_ORI", map_editor.buffer, car, is_mod=False)
        
        if ok: self.log(f"Backup salvato in archivio: {fname}")
        else: self.log(f"Errore salvataggio: {fname}")
        
        self.status = "Finito"; self.is_working = False

    def _sim_write(self, map_editor):
        # CONTROLLO SICUREZZA PRE-FLASH
        car = self.db.get_current_specs()
        
        # 1. Controllo se c'è un file
        if not map_editor.is_loaded:
            self.log("ERRORE: Nessun file caricato!"); self.is_working=False; return

        # 2. Controllo coerenza HW (Simulato usando metadata se presenti)
        if map_editor.current_metadata:
            file_hw = map_editor.current_metadata.get('ecu_hw', 'Unknown')
            if file_hw != car['ecu_hw']:
                self.log(f"❌ BLOCCO SICUREZZA: Mismatch HW!")
                self.log(f"File: {file_hw} vs ECU: {car['ecu_hw']}")
                self.log("Scrittura annullata per prevenire brick."); self.is_working=False; return
        
        self.log("Controllo Checksum... OK")
        self.log(f"Scrittura su {car['ecu_hw']}...")
        time.sleep(1)
        for i in range(101):
            self.progress = i; self.status = f"Scrittura {i}%"; time.sleep(0.03)
        self.status = "Finito"; self.is_working = False; self.log("Scrittura completata con successo.")

# --- API ---
class Api:
    def __init__(self):
        self.db = CarDatabase(); self.lib = MapLibrary()
        self.physics = PhysicsEngine(self.db)
        self.flasher = FlashManager(self.db, self.lib)
        self.editor = MapEditor()
        self.sim_window = None; self.app_mode = 'sim'

    # --- MAP LIBRARY API ---
    def get_library_maps(self): return self.lib.get_all_maps()
    def delete_library_map(self, fname): return self.lib.delete_map(fname)
    
    def load_map_from_library(self, fname):
        data, meta = self.lib.load_map_data(fname)
        if data:
            self.editor.load_from_bytes(data, fname, meta)
            return {"status": "success", "msg": f"Caricato: {fname}"}
        return {"status": "error", "msg": "Errore caricamento file"}

    def save_current_map(self, name_suffix):
        if not self.editor.is_loaded: return {"status":"error", "msg":"Nessun dato"}
        car = self.db.get_current_specs() # Usa auto corrente per metadata
        # Se stiamo salvando una mod, usiamo i metadati originali se ci sono, altrimenti quelli dell'auto corrente
        base_car = self.editor.current_metadata if self.editor.current_metadata else car
        
        ok, fname = self.lib.save_map(f"{base_car['name']}_{name_suffix}", self.editor.buffer, base_car, is_mod=True)
        if ok: return {"status":"success", "msg":f"Salvato: {fname}"}
        return {"status":"error", "msg":fname}

    # --- TUNING API ---
    def read_ecu(self): 
        self.flasher.start_read(self.editor); return {"msg": "OK"}
    def write_ecu(self):
        self.flasher.start_write(self.editor); return {"status":"success"}
    def apply_wizard_stage(self, stage):
        if self.editor.apply_stage(stage): return {"status":"success"}
        return {"status":"error", "msg":"Nessun file caricato"}
    def get_hex_view(self, offset): return self.editor.get_hex_chunk(int(offset))
    def update_hex(self, offset, val): return self.editor.write_byte(int(offset), int(val, 16))
    
    def get_flash_status(self):
        return {"progress": self.flasher.progress, "status": self.flasher.status, "logs": self.flasher.log_msg, "working": self.flasher.is_working, "file_loaded": self.editor.is_loaded, "filename": self.editor.current_filename}

    # --- SIMULATOR & MAIN ---
    def get_available_cars(self): return self.db.cars
    def select_sim_car(self, car_id): self.physics.load_new_car(car_id); return self.db.get_current_specs()
    def get_data(self): return self.physics.get_state()
    def get_ecu_info(self): return self.db.get_current_specs()
    def get_sim_state(self): return self.physics.get_state()
    def get_ports(self): return ["SIMULATORE"] if self.app_mode == 'sim' else ["COM_REALE"]
    def connect_ecu(self, p): return {"status":"success"}
    def disconnect(self): return {"status":"success"}
    
    def sim_control(self, t, b, s, i): 
        try:
            if t is not None: self.physics.throttle = float(t)
            if b is not None: self.physics.brake = float(b)
        except: pass
        if i is not None: self.physics.engine_on = bool(i)
        if s is not None: self.physics.gear_selector = str(s)

    def open_sim(self):
        if self.sim_window:
            try: self.sim_window.show(); return
            except: self.sim_window = None
        self.sim_window = webview.create_window('Garage Simulatore', 'simulator.html', js_api=self, width=500, height=750, resizable=True)

    def set_mode(self, mode):
        self.app_mode = mode
        if mode == 'sim': threading.Timer(0.1, self.open_sim).start()

if __name__ == '__main__':
    api = Api()
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    webview.create_window('ECU Tuner Suite v4', 'index.html', js_api=api, width=1250, height=900, background_color='#0a0a0a')
    webview.start(debug=False, gui='qt')