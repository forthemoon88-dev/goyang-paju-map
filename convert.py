#!/usr/bin/env python3
"""
KMZ → JSON 변환 스크립트
사용법: python convert.py 파일명.kmz [그룹명] [색상] [레이어타입]

예시:
  python convert.py 새노선.kmz "새 노선" "#ef4444" road
  python convert.py 환경구역.kmz "환경평가" "#22d3ee" env
  python convert.py 필지.kmz "덕양구필지" "#60a5fa" parcel

레이어타입:
  road    - 도로/노선 (선/폴리곤)
  dev     - 도시개발 구역 (폴리곤)
  env     - 환경 (폴리곤/마커)
  parcel  - 필지 (타일 분할 저장)
  other   - 기타
"""

import sys, os, re, json, math, zipfile, shutil

def parse_kmz(kmz_path):
    tmp = '/tmp/_kmz_convert'
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with zipfile.ZipFile(kmz_path, 'r') as z:
        z.extractall(tmp)
    kml_path = None
    for root, dirs, files in os.walk(tmp):
        for f in files:
            if f.endswith('.kml'):
                kml_path = os.path.join(root, f)
                break
    if not kml_path:
        raise Exception("KML 파일을 찾을 수 없습니다")
    return open(kml_path, encoding='utf-8').read()

def parse_features(kml, layer_type):
    features = []

    # Placemark 파싱
    for pm in re.findall(r'<Placemark>(.*?)</Placemark>', kml, re.DOTALL):
        name_m = re.search(r'<name>(.*?)</name>', pm)
        name = name_m.group(1).strip() if name_m else ''
        coords_m = re.search(r'<coordinates>(.*?)</coordinates>', pm, re.DOTALL)
        if not coords_m: continue

        pts = coords_m.group(1).strip().split()
        converted = []
        for p in pts:
            parts = p.split(',')
            if len(parts) >= 2:
                try:
                    converted.append([round(float(parts[1]),6), round(float(parts[0]),6)])
                except: pass
        if len(converted) < 1: continue

        if '<Polygon>' in pm:
            geom = 'polygon'
        elif '<LineString>' in pm:
            geom = 'line'
        else:
            geom = 'marker'

        # 필지 타입이면 ExtendedData 속성 파싱
        attrs = {}
        if layer_type == 'parcel':
            ext_m = re.search(r'<ExtendedData>(.*?)</ExtendedData>', pm, re.DOTALL)
            if ext_m:
                attrs = dict(re.findall(r'<SimpleData name="(.*?)">(.*?)</SimpleData>', ext_m.group(1)))

        features.append({
            'name': name,
            'geom': geom,
            'coords': converted,
            'attrs': attrs
        })

    # GroundOverlay → 마커
    for go in re.findall(r'<GroundOverlay>(.*?)</GroundOverlay>', kml, re.DOTALL):
        name_m = re.search(r'<name>(.*?)</name>', go)
        n_m = re.search(r'<north>(.*?)</north>', go)
        s_m = re.search(r'<south>(.*?)</south>', go)
        e_m = re.search(r'<east>(.*?)</east>', go)
        w_m = re.search(r'<west>(.*?)</west>', go)
        if not (name_m and n_m and s_m and e_m and w_m): continue
        lat = (float(n_m.group(1))+float(s_m.group(1)))/2
        lng = (float(e_m.group(1))+float(w_m.group(1)))/2
        features.append({
            'name': name_m.group(1).strip(),
            'geom': 'marker',
            'coords': [[round(lat,6), round(lng,6)]],
            'attrs': {}
        })

    return features

def save_parcel_tiles(features, out_dir):
    """필지는 타일별로 분할 저장"""
    TILE = 0.02
    os.makedirs(out_dir, exist_ok=True)
    grid = {}

    for f in features:
        if not f['coords']: continue
        lat = sum(pt[0] for pt in f['coords']) / len(f['coords'])
        lng = sum(pt[1] for pt in f['coords']) / len(f['coords'])
        tk = f"{math.floor(lat/TILE)*TILE:.2f}_{math.floor(lng/TILE)*TILE:.2f}"
        if tk not in grid: grid[tk] = []
        a = f['attrs']
        grid[tk].append([
            a.get('A3',''),   # 주소
            a.get('A7',''),   # 지목
            round(float(a.get('A12',0) or 0)),  # 면적
            a.get('A14',''),  # 용도지역
            a.get('A18',''),  # 이용상황
            int(a.get('A25',0)) if str(a.get('A25','')).isdigit() else 0,  # 공시지가
            round(lat,5), round(lng,5)
        ])

    for tk, data in grid.items():
        path = f'{out_dir}/{tk}.json'
        # 기존 파일과 병합
        existing = []
        if os.path.exists(path):
            existing = json.load(open(path))
        combined = existing + data
        with open(path, 'w', encoding='utf-8') as f2:
            json.dump(combined, f2, ensure_ascii=False, separators=(',',':'))

    print(f"  필지 타일: {len(grid)}개")
    return len(grid)

def update_layers(group_id, label, color, layer_type, filename):
    """layers.json 자동 업데이트"""
    layers_path = 'data/layers.json'
    layers = []
    if os.path.exists(layers_path):
        layers = json.load(open(layers_path))

    # 기존 항목 업데이트 또는 추가
    existing = next((l for l in layers if l['id'] == group_id), None)
    if existing:
        existing.update({'label': label, 'color': color, 'type': layer_type, 'file': filename})
    else:
        layers.append({
            'id': group_id,
            'label': label,
            'color': color,
            'type': layer_type,
            'file': filename,
            'visible': True
        })

    with open(layers_path, 'w', encoding='utf-8') as f:
        json.dump(layers, f, ensure_ascii=False, indent=2)
    print(f"  layers.json 업데이트: {len(layers)}개 레이어")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    kmz_path = sys.argv[1]
    group_name = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(os.path.basename(kmz_path))[0]
    color = sys.argv[3] if len(sys.argv) > 3 else '#60a5fa'
    layer_type = sys.argv[4] if len(sys.argv) > 4 else 'other'

    group_id = re.sub(r'[^\w]', '_', group_name)

    print(f"\n변환 시작: {kmz_path}")
    print(f"  그룹: {group_name} ({layer_type})")

    kml = parse_kmz(kmz_path)
    features = parse_features(kml, layer_type)
    print(f"  피처: {len(features)}개")

    os.makedirs('data/kmz', exist_ok=True)
    os.makedirs('data/parcels', exist_ok=True)

    if layer_type == 'parcel':
        save_parcel_tiles(features, 'data/parcels')
        update_layers(group_id, group_name, color, layer_type, 'data/parcels')
    else:
        out = {
            'group': group_id,
            'label': group_name,
            'color': color,
            'type': layer_type,
            'features': features
        }
        fname = f'data/kmz/{group_id}.json'
        with open(fname, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, separators=(',',':'))
        size = os.path.getsize(fname)
        print(f"  저장: {fname} ({size/1024:.0f}KB)")
        update_layers(group_id, group_name, color, layer_type, fname)

    print(f"\n✅ 완료! GitHub에 data/ 폴더를 업로드하세요.")

if __name__ == '__main__':
    main()
