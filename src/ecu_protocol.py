import serial
import time

class OBDConnection:
    def __init__(self, port):
        self.port = port
        self.ser = None
        self.connected = False
        self.connect()

    def connect(self):
        try:
            self.ser = serial.Serial(self.port, 38400, timeout=1)
            # Sequenza di inizializzazione ELM327 standard
            cmds = ["ATZ", "ATE0", "ATSP0"] 
            for c in cmds:
                self._send_raw(c)
                time.sleep(0.2)
            self.connected = True
        except Exception as e:
            print(f"Errore connessione OBD: {e}")
            self.connected = False
            raise e

    def close(self):
        if self.ser:
            self.ser.close()
        self.connected = False

    def _send_raw(self, cmd):
        if not self.ser: return ""
        self.ser.write((cmd + '\r').encode())
        # Legge finché non trova il carattere '>' (prompt ELM)
        return self.ser.read_until(b'>').decode('utf-8', errors='ignore').strip().replace('>', '')

    def get_data(self):
        if not self.connected:
            return {"rpm": 0, "speed": 0, "temp": 0, "gear": "-", "engine_on": False, "simulated": False}

        data = {
            "rpm": 0, "speed": 0, "temp": 0, 
            "gear": "D", "engine_on": True, "simulated": False
        }

        try:
            # Richiediamo RPM (010C) e Velocità (010D)
            # Nota: In un'app pro, queste richieste andrebbero fatte in un thread separato
            # per non rallentare l'interfaccia, ma per ora va bene così.
            
            # --- RPM ---
            res_rpm = self._send_raw("010C") 
            # Parse es: "41 0C 1A F8"
            if "41 0C" in res_rpm:
                parts = res_rpm.split()
                # Trova indice header
                try:
                    i = parts.index("41")
                    if parts[i+1] == "0C":
                        val = (int(parts[i+2], 16) * 256 + int(parts[i+3], 16)) / 4
                        data["rpm"] = int(val)
                except: pass

            # --- SPEED ---
            res_spd = self._send_raw("010D")
            if "41 0D" in res_spd:
                parts = res_spd.split()
                try:
                    i = parts.index("41")
                    data["speed"] = int(parts[i+2], 16)
                except: pass

        except Exception as e:
            print(f"Errore lettura dati: {e}")
            
        return data