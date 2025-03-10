
# Ecommerce Map Project

A Project for Ecommerce MAP


## Installation
Install python 3.11
Install project with venv

```bash
  python3 -m venv venv
  # activate the venv
  cd venv/scripts/activate

  
  # for mac
   source venv/bin/activate
 
   pip Install -r requirements.txt
 ```

  python3 manage.py runserver


## Useful Commands
```
python3 manage.py makemigrations
python3 manage.py migrate

python3 manage.py createsuperuser
admin credentials:
username: admin
pwd : admin
```
## Run PYGISTODXF File
```
python manage.py export_gis_dxf -26.68249618 152.95859959 "your path system absoulte path\EcommerceMap\\test2.dxf"
```

## Database Setup 
```
Install  Postgis extension so database can work with spatial data
        'NAME': 'ecommerce_map_db',
        'USER': 'postgres',
        'PASSWORD': '123456',
```
## GDAL (Geospatial Data Abstraction Library) in linux
```
 ```
`purpose of using this to make smooth transition for downloading the file in dxf.` 
```
sudo apt install gdal-bin libgdal-dev python3-gdal
```

## GDAL (Geospatial Data Abstraction Library) in Window
```
    use this file inside the proect directory -> pip install GDAL -3.4.3-cp311-cp11-win_amd64.whl 
    # changing in setting file line # 143 and # 144
    GDAL_LIBRARY_PATH = r'C:\Users\YourUserName\XYZDIRECTORY\EcommerceMap\.venv\Lib\site-packages\osgeo\gdal304.dll'
    GEOS_LIBRARY_PATH = r'C:\Users\YourUsername\XYZDIRECTORY\EcommerceMap\.venv\Lib\site-packages\osgeo\geos_c.dll' 
    
```