import numpy as np

# Demo: Analyze current statistics with numpy
stats = {
    'toplam_sorgulama': 22,
    'toplam_deneme': 25,
    'basarili_deneme': 14,
    'basarisiz_deneme': 11,
}

# Convert to numpy array for analysis
values = np.array(list(stats.values()))
labels = np.array(list(stats.keys()))

print("=== NumPy Analizi ===")
print("Değerler:", values)
print("Ortalama deneme sayısı:", np.mean(values))
print("Median:", np.median(values))
print("Standart sapma:", np.std(values))
print("Max değer:", np.max(values), "-", labels[np.argmax(values)])
print("Min değer:", np.min(values), "-", labels[np.argmin(values)])

# Success rate calculation
success_rate = stats['basarili_deneme'] / stats['toplam_deneme']
print("\nBaşarı oranı:", success_rate)
print("NumPy ile hesaplama:", np.round(success_rate, 3))

# Error pattern analysis
print("\n=== Hata Pattern Analizi ===")
errors = {'MOV': 11, 'ADD': 2, 'XOR': 2}
error_values = np.array(list(errors.values()))
error_labels = np.array(list(errors.keys()))
print("En çok hata:", error_labels[np.argmax(error_values)])
print("Hata dağılımı percentage:", np.round(error_values / error_values.sum() * 100, 1))