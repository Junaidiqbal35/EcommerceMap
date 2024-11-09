
# Ecommerce Map Project

A Project for Ecommerce MAP


## Installation
Install python > 3.8
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