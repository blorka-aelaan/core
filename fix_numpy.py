#!/usr/bin/env python3
import re

with open('/home/emrah/Genel/core/uzuv/asm_uzuv.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the position after "self.log(\"guncelle_yok\", not_=\"yeni hata kaydı bulmadı\")"
target = 'self.log(\"guncelle_yok\", not_=\"yeni hata kaydı bulmadı\")'
idx = content.find(target)
if idx >= 0:
    # Find the end of this line
    line_end = content.find('\n', idx)
    after_line = content[line_end+1:]
    
    # The new method to insert
    new_method = '''
    def numpy_istatistik_analizi(self):
        import numpy as np
        stats = dict(self.istatistikler)
        success_rate = stats['basarili_deneme'] / stats['toplam_deneme'] if stats['toplam_deneme'] > 0 else 0
        analysis = {
            'success_rate': float(success_rate),
            'error_distribution': {},
            'most_error_prone': None,
            'performance_score': 0.0,
            'recommendations': []
        }
        if self.hata_dersleri:
            error_patterns = list(self.hata_dersleri.keys())
            error_counts = np.array([self.hata_dersleri.get(p, 0) for p in error_patterns])
            error_pct = np.round(error_counts / error_counts.sum() * 100, 1)
            for i, pattern in enumerate(error_patterns):
                analysis['error_distribution'][pattern] = float(error_pct[i])
            if len(error_counts) > 0:
                most_error_idx = np.argmax(error_counts)
                analysis['most_error_prone'] = error_patterns[most_error_idx]
            success_counts = np.array([self.syntax_basari.get(p, 0) for p in error_patterns])
            analysis['success_by_pattern'] = {p: int(c) for p, c in zip(error_patterns, success_counts)}
        analysis['performance_score'] = float(np.round(success_rate, 3))
        if success_rate < 0.5:
            analysis['recommendations'].append("Daha fazla pratiği yapin - basari orani dusuk")
            if 'MOV' in self.hata_dersleri:
                analysis['recommendations'].append("MOV komutundan daha fazla pratiği yapin")
        elif success_rate < 0.7:
            analysis['recommendations'].append("Orta seviyede progress - some areas need attention")
        else:
            analysis['recommendations'].append("Harika! Temel asmanya hakimsiniz, ileri seviye konulara gecin")
        all_known_patterns = set(self.KOMUTLAR.keys()) | set(self.REGISTERLER.keys())
        missing = all_known_patterns - set(self.hata_dersleri.keys()) - set(self.syntax_basari.keys())
        if missing:
            analysis['available_to_learn'] = list(missing)[:10]
        return analysis
'''
    
    # Insert after the target line
    new_content = content[:line_end+1] + new_method + after_line
    
    with open('/home/emrah/Genel/core/uzuv/asm_uzuv.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Successfully added numpy_istatistik_analizi")
else:
    print("Target text not found!")
    print("Looking for:", repr(target[:50]))