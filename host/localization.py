import numpy as np

class LocalizationSystem:
    def __init__(self, mode='simulated'):
        self.mode = mode
        self.speed_of_sound = 1540.0 # m/s
        self.mic_positions = {
            'Superior Patella': np.array([0.0, 0.04]),
            'Inferior Patella': np.array([0.0, -0.04]),
            'Medial Joint Line': np.array([-0.03, 0.0]),
            'Lateral Joint Line': np.array([0.03, 0.0])
        }
        self.calibration_fingerprints = {}
        
    def simulate_event(self, source_pos):
        delays = []
        amplitudes = []
        for name, pos in self.mic_positions.items():
            dist = np.linalg.norm(pos - source_pos)
            delay = dist / self.speed_of_sound
            amplitude = 1.0 / (dist + 1e-3)
            
            # Add noise
            delay += np.random.normal(0, 1e-6)
            amplitude *= np.random.normal(1.0, 0.1)
            
            delays.append(delay)
            amplitudes.append(amplitude)
            
        # Normalize
        amplitudes = np.array(amplitudes)
        amplitudes /= np.linalg.norm(amplitudes)
        
        return np.array(delays), amplitudes
        
    def calibrate_simulated(self):
        for name, pos in self.mic_positions.items():
            fps = []
            for _ in range(5):
                delays, amps = self.simulate_event(pos)
                fps.append(np.concatenate([delays, amps]))
            self.calibration_fingerprints[name] = np.mean(fps, axis=0)
            
    def classify(self, delays, amplitudes):
        if not self.calibration_fingerprints:
            return 'Unknown', 0.0
            
        fp = np.concatenate([delays, amplitudes])
        best_match = None
        min_dist = float('inf')
        
        for name, cal_fp in self.calibration_fingerprints.items():
            dist = np.linalg.norm(fp - cal_fp)
            if dist < min_dist:
                min_dist = dist
                best_match = name
                
        confidence = np.clip(1.0 - min_dist, 0.0, 1.0)
        return best_match, confidence
        
    def run_simulated_demo(self):
        self.calibrate_simulated()
        
        results = []
        sources = list(self.mic_positions.keys())
        
        # 40 test events, biased medial
        test_dist = ['Medial Joint Line']*16 + ['Lateral Joint Line']*8 + ['Superior Patella']*8 + ['Inferior Patella']*8
        
        correct = 0
        for src in test_dist:
            delays, amps = self.simulate_event(self.mic_positions[src])
            pred, conf = self.classify(delays, amps)
            if pred == src:
                correct += 1
            results.append((src, pred))
            
        acc = correct / len(test_dist)
        return acc, results
