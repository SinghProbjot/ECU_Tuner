import webview
import serial.tools.list_ports
import time
import threading
import random

# --- MOTORE FISICO (Il cuore del Simulatore) ---
class PhysicsEngine:
    def __init__(self):
        self.engine_on = False
        self.rpm = 0
        self.speed = 0
        self.gear = 0 # 0=N
        self.throttle = 0.0
        self.brake = 0.0
        self.lock = threading.Lock()
        
        # Mappa Motore (Coppia vs RPM) - Questa è quella che mapperai in futuro!
        self.torque_curve = {1000: 0.5, 3000: 0.9, 6000: 0.7, 7500: 0.1}
        
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            with self.lock:
                if not self.engine_on:
                    self.rpm = max(0, self.rpm - 150)
                    self.speed = max(0, self.speed - 1)
                else:
                    # Fisica super-semplificata
                    if self.gear == 0: # Folle
                        target = 850 + (self.throttle * 6500)
                        self.rpm += (target - self.rpm) * 0.15
                        self.speed -= 0.5
                    else:
                        # In marcia
                        ratio = [0, 100, 60, 40, 30, 25, 20][self.gear]
                        # Accelerazione basata su mappa coppia
                        torque = self.torque_curve.get(int(self.rpm/1000)*1000, 0.5)
                        accel = self.throttle * torque * 5
                        decel = self.brake * 10 + 0.5 # Freno + Attrito
                        
                        self.speed += (accel - decel) * 0.05
                        self.speed = max(0, self.speed)
                        self.rpm = max(850, self.speed * ratio)
                
                # Limiti
                if self.rpm > 7500: self.rpm = 7400 # Limitatore
                self.rpm = int(self.rpm)
                self.speed = int(self.speed)
            
            time.sleep(0.05)

    def set_controls(self, th, br, sh, ign):
        with self.lock:
            self.throttle = float(th)
            self.brake = float(br)
            if ign is not None: self.engine_on = ign
            if sh != 0: 
                self.gear += sh
                self.gear = max(0, min(6, self.gear))

# --- CAVO VIRTUALE (Simula il chip ELM327) ---
class VirtualELM327:
    def __init__(self, physics):
        self.physics = physics
        self.connected = True

    def write(self, data):
        # Simula l'invio del comando
        pass

    def read_response(self, command):
        # Qui avviene la magia: TRADUZIONE FISICA -> ESADECIMALE
        # L'app principale crede di parlare con un chip vero!
        
        cmd = command.strip().upper()
        
        if cmd == "ATZ": return "ELM327 v2.1"
        if cmd == "ATSP0": return "OK"
        
        with self.physics.lock:
            rpm = self.physics.rpm
            speed = self.physics.speed
            temp = 90 if self.physics.engine_on else 20

        # Richiesta RPM (010C)
        if "010C" in cmd:
            # Formula inversa: RPM = (A*256 + B) / 4
            val = rpm * 4
            A = int(val // 256)
            B = int(val % 256)
            # Risponde come un vero OBD: "41 0C A B"
            return f"41 0C {A:02X} {B:02X}"
            
        # Richiesta Velocità (010D)
        if "010D" in cmd:
            return f"41 0D {speed:02X}"
            
        return "NO DATA"

# --- GESTORE CONNESSIONE REALE ---
class RealELM327:
    def __init__(self, port):
        self.ser = serial.Serial(port, 38400, timeout=1)
        self.ser.write(b"ATZ\r")
        time.sleep(1)
        self.ser.read_all()
        self.ser.write(b"ATSP0\r")
        time.sleep(0.5)
        self.ser.read_all()

    def read_response(self, command):
        self.ser.write((command + "\r").encode())
        time.sleep(0.1)
        return self.ser.read_all().decode('utf-8', errors='ignore').strip().replace('>', '')

    def close(self):
        self.ser.close()

# --- API BRIDGE ---
class Api:
    def __init__(self):
        self.physics = PhysicsEngine()
        self.connection = None
        self.sim_window = None

    # --- METODI MAIN APP ---
    def get_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        ports.insert(0, "SIMULATORE_VIRTUALE")
        return ports

    def connect_ecu(self, port):
        if self.connection:
            try: self.connection.close()
            except: pass
            
        if port == "SIMULATORE_VIRTUALE":
            self.connection = VirtualELM327(self.physics)
            return {"status": "success", "msg": "Connesso a ECU Virtuale"}
        else:
            try:
                self.connection = RealELM327(port)
                return {"status": "success", "msg": f"Connesso a {port}"}
            except Exception as e:
                return {"status": "error", "msg": str(e)}

    def get_data(self):
        # L'app principale chiama questo. 
        # NOTA: Qui simuliamo il comportamento "grezzo" dell'app che deve decodificare
        # Se siamo connessi, inviamo comandi OBD standard
        
        if not self.connection:
            return {"rpm": 0, "speed": 0, "raw": "DISCONNECTED"}
            
        try:
            # 1. Chiedi RPM
            raw_rpm = self.connection.read_response("010C")
            
            # 2. Chiedi Velocità
            raw_spd = self.connection.read_response("010D")
            
            # 3. Decodifica (Questo lo farebbe l'app client normalmente)
            rpm = 0
            if "41 0C" in raw_rpm:
                parts = raw_rpm.split()
                # Trova i byte esadecimali (logica semplificata)
                # Nel virtuale arriva pulito "41 0C XX XX", nel reale potrebbe esserci sporcizia
                hex_parts = [p for p in parts if len(p)==2]
                try:
                    idx = hex_parts.index("41")
                    if hex_parts[idx+1] == "0C":
                        A = int(hex_parts[idx+2], 16)
                        B = int(hex_parts[idx+3], 16)
                        rpm = ((A * 256) + B) / 4
                except: pass

            speed = 0
            if "41 0D" in raw_spd:
                parts = raw_spd.split()
                hex_parts = [p for p in parts if len(p)==2]
                try:
                    idx = hex_parts.index("41")
                    speed = int(hex_parts[idx+2], 16)
                except: pass

            return {"rpm": int(rpm), "speed": int(speed), "raw": raw_rpm}

        except Exception as e:
            return {"rpm": 0, "speed": 0, "raw": "ERR"}

    def disconnect(self):
        self.connection = None

    # --- METODI SIMULATORE ---
    def open_simulator_window(self):
        if not self.sim_window:
            self.sim_window = webview.create_window(
                'Simulatore di Guida', 'simulator.html', 
                js_api=self, width=600, height=800
            )
        else:
            self.sim_window.show()

    def sim_control(self, th, br, sh, ign):
        # Questo metodo viene chiamato SOLO dalla finestra simulatore
        self.physics.set_controls(th, br, sh, ign)
    
    def get_sim_state(self):
        # Dati per aggiornare la grafica del simulatore (non dell'ECU Tuner!)
        with self.physics.lock:
            return {
                "rpm": self.physics.rpm,
                "speed": self.physics.speed,
                "gear": self.physics.gear,
                "engine_on": self.physics.engine_on
            }

if __name__ == '__main__':
    api = Api()
    # Finestra Principale (ECU Tuner)
    webview.create_window(
        'ECU Tuner Studio (Main)', 'index.html', 
        js_api=api, width=1000, height=700, background_color='#0a0a0a'
    )
    webview.start(debug=True)