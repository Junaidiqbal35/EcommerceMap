
# Map GIS Project

Project Summary: GIS Layer Download & Export System
What It Is
A python-django based web application that allows users to browse, preview, and download GIS infrastructure layers from multiple ArcGIS REST servers, with data export capabilities to DXF/CAD format.

Core Functionality:

Layer Browser: Users can search and filter infrastructure layers (water, electric, roads, etc.) from configured ArcGIS servers
Map Preview: Interactive map showing layer data before download with zoom-to-layer functionality
Credits System: Users spend "connects" (credits) to download layers
Export System: Downloads layer data as DXF files for CAD software, with Australian coordinate system conversion (GDA2020/GDA94)
Nearby Search: Click-to-find layers near specific map locations

Key Components

Server Management: Configures multiple ArcGIS REST service endpoints
Layer Catalog: 68+ layers across 25+ servers with metadata and geometry info
Download Tracking: Records user downloads with location/timestamp
Coordinate Conversion: Automatic projection to appropriate Australian MGA zones
DXF Generation: Creates CAD-compatible files with proper symbology and labeling

Target Users
Infrastructure professionals, surveyors, and GIS analysts who need to access and download utility/infrastructure data for CAD workflows in Australia.
Technical Stack
Django + PostGIS, Leaflet maps, ArcGIS REST API integration, HTMX for dynamic UI, DXF export via ezdxf library.


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




# Build Docker images
docker-compose build

# Run django command in the container
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser

# Start the containers
docker-compose up 

# Check logs (if needed)
docker-compose logs -f
