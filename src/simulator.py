import time
import threading
import random

class CarPhysicsEngine:
    def __init__(self):
        # Stato veicolo
        self.engine_on = False
        self.rpm = 0
        self.speed_kmh = 0
        self.gear = 0  # 0=N, 1-6
        self.throttle = 0.0
        self.brake = 0.0
        
        # --- DATI DI CALIBRAZIONE (La "Mappa") ---
        # In futuro modificheremo questi valori dall'interfaccia
        # Chiave: Giri Motore, Valore: Coppia (0.0 a 1.0)
        self.torque_map = {
            1000: 0.4,
            2000: 0.6,
            3000: 0.8, # Picco di coppia
            4000: 0.9,
            5000: 0.85,
            6000: 0.7,
            7000: 0.5
        }
        
        # Costanti Fisiche
        self.IDLE_RPM = 850
        self.MAX_RPM = 7200
        self.GEAR_RATIOS = [0, 120, 75, 50, 38, 30, 24] 
        self.TIRE_DRAG = 0.5
        self.WIND_DRAG = 0.005
        
        # Loop thread
        self.running = True
        self.lock = threading.Lock()
        threading.Thread(target=self._physics_loop, daemon=True).start()

    def _get_torque_from_map(self, current_rpm):
        # Cerca nella mappa la coppia disponibile per questi giri
        # Semplificazione: prende il valore più vicino (in futuro: interpolazione lineare)
        available_rpms = list(self.torque_map.keys())
        closest_rpm = min(available_rpms, key=lambda x: abs(x - current_rpm))
        return self.torque_map[closest_rpm]

    def _physics_loop(self):
        while self.running:
            with self.lock:
                dt = 0.05
                
                if not self.engine_on:
                    self.rpm = max(0, self.rpm - 100)
                    self.speed_kmh = max(0, self.speed_kmh - 0.5)
                else:
                    if self.gear == 0: # FOLLE
                        target = self.IDLE_RPM + (self.throttle * (self.MAX_RPM - self.IDLE_RPM))
                        if self.rpm < target: self.rpm += (target - self.rpm) * 0.2
                        else: self.rpm += (target - self.rpm) * 0.1
                        self.speed_kmh -= self.TIRE_DRAG * 0.2
                    else:
                        # MARCIA INSERITA
                        ratio = self.GEAR_RATIOS[self.gear]
                        
                        # 1. Leggiamo la mappa motore (Quella che mapperai!)
                        engine_torque_curve = self._get_torque_from_map(self.rpm)
                        
                        # 2. Calcoliamo accelerazione
                        force = self.throttle * engine_torque_curve
                        accel = force * (ratio * 0.06)
                        
                        # 3. Resistenze
                        drag = self.TIRE_DRAG + (self.speed_kmh**2 * self.WIND_DRAG)
                        braking = self.brake * 15.0
                        
                        self.speed_kmh += (accel - drag - braking) * dt
                        self.speed_kmh = max(0, self.speed_kmh)
                        
                        # 4. RPM vincolati alle ruote
                        self.rpm = self.speed_kmh * ratio
                        if self.rpm < self.IDLE_RPM and self.speed_kmh > 2:
                            self.rpm = self.IDLE_RPM # Anti-stall

                # Limiti
                self.rpm = max(0, min(self.rpm, self.MAX_RPM))
            
            time.sleep(dt)

    # API per l'app
    def input_control(self, th, br, shift, ign):
        with self.lock:
            self.throttle = float(th)
            self.brake = float(br)
            if ign: self.engine_on = not self.engine_on
            if shift != 0:
                new_g = self.gear + int(shift)
                if 0 <= new_g <= 6: self.gear = new_g

    def get_data(self):
        with self.lock:
            return {
                "rpm": int(self.rpm),
                "speed": int(self.speed_kmh),
                "temp": 90 if self.engine_on else 20,
                "gear": self.gear,
                "engine_on": self.engine_on,
                "simulated": True
            }