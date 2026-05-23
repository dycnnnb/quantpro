import urllib.request, zipfile, os

url = 'https://github.com/XTLS/Xray-core/releases/latest/download/Xray-windows-64.zip'
zip_path = 'tools/xray.zip'
extract_dir = 'tools/xray'

os.makedirs(extract_dir, exist_ok=True)
exe_path = os.path.join(extract_dir, 'xray.exe')

if os.path.exists(exe_path):
    print('xray.exe already exists')
else:
    print('Downloading Xray-core...')
    urllib.request.urlretrieve(url, zip_path)
    print('Extracting...')
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(extract_dir)
    os.remove(zip_path)
    print('Done:', exe_path)
