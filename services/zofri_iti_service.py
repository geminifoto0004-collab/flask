"""
ZOFRI 和 ITI 數據獲取服務
功能：從 ZOFRI 和 ITI 網站獲取數據
"""

import requests
import json
import pandas as pd
import re
from bs4 import BeautifulSoup
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_container_from_document(codigo, cookies_dict):
    """
    通過101-編號獲取集裝箱號
    
    Args:
        codigo: 101-開頭的文檔編號
        cookies_dict: 登入後的cookies
        
    Returns:
        清理後的集裝箱號，或 None
    """
    try:
        # 構造獲取文檔詳情的URL
        timestamp = int(time.time() * 1000)
        detail_url = f"https://zvirtual.zofri.cl/controller?accion=documentosObtener&codigoDoc={codigo}&_={timestamp}"
        # print(f"正在獲取文檔 {codigo} 的詳情...")
        
        response = requests.get(
            detail_url,
            cookies=cookies_dict,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': 'https://zvirtual.zofri.cl/busquedadocumento'
            },
            timeout=30,
            verify=False
        )
        
        if response.status_code != 200:
            # print(f"❌ 獲取文檔詳情失敗，狀態碼: {response.status_code}")
            return None
        
        # print(f"詳情響應內容: {response.text[:500]}")
        
        # 從JSON響應中提取contenedor字段
        try:
            detail_data = response.json()
            container_number = None
            
            # 查找contenedor字段（可能在不同的層級）
            if isinstance(detail_data, dict):
                # 直接在根層級
                if 'contenedor' in detail_data:
                    container_number = detail_data['contenedor']
                # 在contenedores數組中
                elif 'contenedores' in detail_data:
                    contenedores = detail_data['contenedores']
                    if isinstance(contenedores, list) and len(contenedores) > 0:
                        if isinstance(contenedores[0], dict) and 'contenedor' in contenedores[0]:
                            container_number = contenedores[0]['contenedor']
                        elif isinstance(contenedores[0], str):
                            container_number = contenedores[0]
                # 在data層級中
                elif 'data' in detail_data:
                    data_obj = detail_data['data']
                    if isinstance(data_obj, dict):
                        if 'contenedor' in data_obj:
                            container_number = data_obj['contenedor']
                        elif 'contenedores' in data_obj:
                            contenedores = data_obj['contenedores']
                            if isinstance(contenedores, list) and len(contenedores) > 0:
                                if isinstance(contenedores[0], dict):
                                    container_number = contenedores[0].get('contenedor') or contenedores[0].get('contenedorNumero')
                                elif isinstance(contenedores[0], str):
                                    container_number = contenedores[0]
            
            if container_number:
                # 清理：去空白、去"-"符號
                container_number = str(container_number).strip().replace('-', '').replace(' ', '')
                # print(f"✅ 找到並清理後的集裝箱號: {container_number}")
                return container_number
            else:
                # print(f"⚠️ 未能從JSON中找到contenedor字段")
                # print(f"JSON結構: {detail_data}")
                return None
                
        except json.JSONDecodeError:
            # print(f"❌ 響應不是有效的JSON格式")
            # print(f"響應內容: {response.text[:500]}")
            return None
            
    except Exception as e:
        # print(f"❌ 獲取集裝箱號時發生錯誤: {e}")
        # import traceback
        # traceback.print_exc()
        return None


def process_data(data, cookies_dict):
    """
    處理文檔數據，通過API獲取集裝箱號用於匹配
    
    Args:
        data: 文檔數據
        cookies_dict: 必須提供的cookies字典
        
    Returns:
        包含完整GLOSA、集裝箱號和匹配用欄位的DataFrame
    """
    df = pd.json_normalize(data['data'])
    filtered_df = df[
        (df['codigo'].str.startswith('101-', na=False)) & 
        (df['estado.nombre'].isin(['VISADO', 'CONTROLADO']))
    ]
    # 🔥 修復：加入 .copy() 避免 SettingWithCopyWarning
    result_df = filtered_df[['codigo', 'estado.nombre', 'glosa']].copy()
    result_df.columns = ['codigo', 'nombre', 'glosa']
    
    # 通過101編號API獲取集裝箱號（用於內部匹配）
    # print("🔄 開始通過API獲取集裝箱號用於匹配...")
    result_df['_container_number'] = result_df['codigo'].apply(
        lambda codigo: get_container_from_document(codigo, cookies_dict) or ''
    )
    
    # 從glosa中提取集裝箱號用於顯示（格式：HAMU3735312）
    def extract_container_code(glosa):
        match = re.match(r'([A-Z]{4}\d{6,7})', str(glosa))
        if match:
            return match.group(1)
        return ''
    
    result_df['glosa_codigo'] = result_df['glosa'].apply(extract_container_code)
    
    # 從glosa中提取描述部分（格式：BUENOS AIRES EXPRESS）
    def extract_description(glosa):
        match = re.match(r'[A-Z]{4}\d{6,7}\s+(.*)', str(glosa))
        if match:
            return match.group(1).strip()
        return str(glosa)
    
    result_df['glosa_descripcion'] = result_df['glosa'].apply(extract_description)
    
    # 移除原始glosa欄位（因為已經拆分成glosa_codigo和glosa_descripcion）
    result_df = result_df.drop(columns=['glosa'])
    
    return result_df


def iti_data():
    """
    從 ITI 網站獲取數據
    
    Returns:
        包含 ITI 數據的列表
    """
    url = 'https://sistemas.iti.cl/swi/programacion-directos-diferidos.aspx'
    session = requests.Session()
    response = session.get(url, verify=False)
    soup = BeautifulSoup(response.text, 'html.parser')

    viewstate = soup.find('input', {'name': '__VIEWSTATE'})['value']
    event_validation = soup.find('input', {'name': '__EVENTVALIDATION'})['value']

    post_data = {
        '__VIEWSTATE': viewstate,
        '__EVENTVALIDATION': event_validation,
    }
    
    post_response = session.post(url, data=post_data, verify=False)
    post_soup = BeautifulSoup(post_response.text, 'html.parser')

    all_data = []
    row_data_map = {}

    tables = post_soup.find_all('table')

    if len(tables) > 1:
        for index, row in enumerate(tables[1].find_all('tr')):
            cells = row.find_all('td')
            row_data = [cell.get_text(strip=True) for cell in cells]
            row_data_map[index] = row_data
            
            buttons = row.find_all('input', {'type': 'image'})
            if buttons:
                for button in buttons:
                    button_name = button['name']
                    button_post_data = {
                        '__VIEWSTATE': viewstate,
                        '__EVENTVALIDATION': event_validation,
                        button_name + '.x': '10',
                        button_name + '.y': '10',
                    }
                    
                    button_response = session.post(url, data=button_post_data, verify=False)
                    if button_response.status_code == 200:
                        button_soup = BeautifulSoup(button_response.text, 'html.parser')
                        new_tables = button_soup.find_all('table')
                        if new_tables:
                            for table in new_tables:
                                for row in table.find_all('tr'):
                                    cells = row.find_all('td')
                                    new_row_data = [cell.get_text(strip=True) for cell in cells]
                                    if len(new_row_data) > 2 and new_row_data[2].isdigit():
                                        new_row_data[2] = new_row_data[2].zfill(6)
                                    if index in row_data_map:
                                        combined_data = [row_data_map[index][0]] + new_row_data
                                        all_data.append(combined_data)

    return all_data

