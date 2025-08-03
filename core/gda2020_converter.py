"""
GDA2020/GDA94 WKID Converter Module

This module provides functionality to determine the appropriate GDA2020 (Geocentric Datum 
of Australia 2020) and optionally GDA94 WKID codes based on latitude and longitude coordinates.

Author: Auto-generated
Usage: 
    from gda2020_converter import GDA2020Converter
    
    converter = GDA2020Converter()
    wkid = converter.get_wkid(-31.9505, 115.8605)  # Perth coordinates - GDA2020 only
    info = converter.get_zone_info(-31.9505, 115.8605, include_gda94=True)  # Both datums
"""

class GDA2020Converter:
    """
    A class for converting latitude/longitude coordinates to GDA2020 and optionally GDA94 WKID codes.
    
    Both GDA2020 and GDA94 use the Map Grid of Australia (MGA) coordinate system with UTM zones.
    Australia spans UTM zones 49-56.
    """
    
    def __init__(self):
        """Initialize the converter with GDA2020 and GDA94 zone mappings."""
        
        # GDA2020 MGA WKID mappings for each UTM zone
        self.gda2020_wkids = {
            49: 7849,  # GDA2020 MGA Zone 49
            50: 7850,  # GDA2020 MGA Zone 50  
            51: 7851,  # GDA2020 MGA Zone 51
            52: 7852,  # GDA2020 MGA Zone 52
            53: 7853,  # GDA2020 MGA Zone 53
            54: 7854,  # GDA2020 MGA Zone 54
            55: 7855,  # GDA2020 MGA Zone 55
            56: 7856,  # GDA2020 MGA Zone 56
        }
        
        # GDA94 MGA WKID mappings for each UTM zone
        self.gda94_wkids = {
            49: 28349,  # GDA94 MGA Zone 49
            50: 28350,  # GDA94 MGA Zone 50
            51: 28351,  # GDA94 MGA Zone 51
            52: 28352,  # GDA94 MGA Zone 52
            53: 28353,  # GDA94 MGA Zone 53
            54: 28354,  # GDA94 MGA Zone 54
            55: 28355,  # GDA94 MGA Zone 55
            56: 28356,  # GDA94 MGA Zone 56
        }
        
        # Zone coverage descriptions
        self.zone_descriptions = {
            49: "Western Australia (western portion)",
            50: "Western Australia (central-western portion)", 
            51: "Western Australia (central-eastern portion), South Australia (western portion)",
            52: "South Australia (central portion), Northern Territory (southern portion)",
            53: "Northern Territory (central portion), South Australia (eastern portion)",
            54: "Queensland (western portion), Northern Territory (eastern portion), New South Wales (western portion)",
            55: "Queensland (central portion), New South Wales (central portion), Victoria (western portion)",
            56: "Queensland (eastern portion), New South Wales (eastern portion), Victoria (eastern portion), Tasmania"
        }
        
        # Australian boundary approximations
        self.aus_bounds = {
            'min_lat': -44,
            'max_lat': -10,
            'min_lon': 113,
            'max_lon': 154
        }
    
    def validate_coordinates(self, latitude, longitude):
        """
        Validate input coordinates.
        
        Args:
            latitude (float): Latitude in decimal degrees (-90 to 90)
            longitude (float): Longitude in decimal degrees (-180 to 180)
        
        Raises:
            ValueError: If coordinates are out of valid range
        """
        if not (-90 <= latitude <= 90):
            raise ValueError("Latitude must be between -90 and 90 degrees")
        if not (-180 <= longitude <= 180):
            raise ValueError("Longitude must be between -180 and 180 degrees")
    
    def is_in_australia(self, latitude, longitude):
        """
        Check if coordinates are within approximate Australian bounds.
        
        Args:
            latitude (float): Latitude in decimal degrees
            longitude (float): Longitude in decimal degrees
        
        Returns:
            bool: True if coordinates are within Australian bounds
        """
        return (self.aus_bounds['min_lat'] <= latitude <= self.aus_bounds['max_lat'] and
                self.aus_bounds['min_lon'] <= longitude <= self.aus_bounds['max_lon'])
    
    def calculate_utm_zone(self, longitude):
        """
        Calculate UTM zone from longitude.
        
        Args:
            longitude (float): Longitude in decimal degrees
        
        Returns:
            int: UTM zone number
        """
        return int((longitude + 180) / 6) + 1
    
    def get_wkid(self, latitude, longitude, datum='gda2020'):
        """
        Get the WKID for given coordinates and datum.
        
        Args:
            latitude (float): Latitude in decimal degrees
            longitude (float): Longitude in decimal degrees
            datum (str): Either 'gda2020' (default) or 'gda94'
        
        Returns:
            int: MGA WKID code, or None if coordinates are outside Australia
        
        Raises:
            ValueError: If latitude/longitude are out of valid range or datum is invalid
        """
        self.validate_coordinates(latitude, longitude)
        
        if datum.lower() not in ['gda2020', 'gda94']:
            raise ValueError("Datum must be either 'gda2020' or 'gda94'")
        
        if not self.is_in_australia(latitude, longitude):
            return None
        
        utm_zone = self.calculate_utm_zone(longitude)
        
        if datum.lower() == 'gda94':
            return self.gda94_wkids.get(utm_zone)
        else:
            return self.gda2020_wkids.get(utm_zone)
    
    def get_zone_info(self, latitude, longitude, include_gda94=False):
        """
        Get detailed zone information for given coordinates.
        
        Args:
            latitude (float): Latitude in decimal degrees
            longitude (float): Longitude in decimal degrees
            include_gda94 (bool): Whether to include GDA94 WKID in the results
        
        Returns:
            dict: Dictionary containing WKID(s), UTM zone, and description, or None if invalid
        """
        gda2020_wkid = self.get_wkid(latitude, longitude, 'gda2020')
        
        if gda2020_wkid is None:
            return None
        
        utm_zone = int(str(gda2020_wkid)[-2:])  # Extract zone from WKID
        
        result = {
            'utm_zone': utm_zone,
            'gda2020_wkid': gda2020_wkid,
            'gda2020_epsg': gda2020_wkid,  # GDA2020 WKIDs are also EPSG codes
            'description': self.zone_descriptions.get(utm_zone, f"UTM Zone {utm_zone}"),
            'coordinates': (latitude, longitude)
        }
        
        if include_gda94:
            gda94_wkid = self.get_wkid(latitude, longitude, 'gda94')
            result.update({
                'gda94_wkid': gda94_wkid,
                'gda94_epsg': gda94_wkid
            })
        
        return result
    
    def get_all_zones(self, include_gda94=False):
        """
        Get information about all available zones.
        
        Args:
            include_gda94 (bool): Whether to include GDA94 WKIDs in the results
        
        Returns:
            dict: Dictionary mapping UTM zones to their WKID(s) and description
        """
        result = {}
        for zone in self.gda2020_wkids.keys():
            zone_info = {
                'gda2020_wkid': self.gda2020_wkids[zone],
                'description': self.zone_descriptions.get(zone, f"UTM Zone {zone}")
            }
            
            if include_gda94:
                zone_info['gda94_wkid'] = self.gda94_wkids[zone]
            
            result[zone] = zone_info
        
        return result
    
    def batch_convert(self, coordinates_list, include_gda94=False):
        """
        Convert multiple coordinate pairs to WKIDs.
        
        Args:
            coordinates_list (list): List of (latitude, longitude) tuples
            include_gda94 (bool): Whether to include GDA94 WKIDs in the results
        
        Returns:
            list: List of dictionaries with coordinate and WKID information
        """
        results = []
        for lat, lon in coordinates_list:
            try:
                info = self.get_zone_info(lat, lon, include_gda94=include_gda94)
                results.append({
                    'input_coordinates': (lat, lon),
                    'success': True,
                    'result': info
                })
            except Exception as e:
                results.append({
                    'input_coordinates': (lat, lon),
                    'success': False,
                    'error': str(e)
                })
        return results


# Convenience functions for direct import
def get_gda2020_wkid(latitude, longitude):
    """
    Convenience function to get GDA2020 WKID without instantiating the class.
    
    Args:
        latitude (float): Latitude in decimal degrees
        longitude (float): Longitude in decimal degrees
    
    Returns:
        int: GDA2020 MGA WKID code, or None if coordinates are outside Australia
    """
    converter = GDA2020Converter()
    return converter.get_wkid(latitude, longitude, 'gda2020')


def get_gda94_wkid(latitude, longitude):
    """
    Convenience function to get GDA94 WKID without instantiating the class.
    
    Args:
        latitude (float): Latitude in decimal degrees
        longitude (float): Longitude in decimal degrees
    
    Returns:
        int: GDA94 MGA WKID code, or None if coordinates are outside Australia
    """
    converter = GDA2020Converter()
    return converter.get_wkid(latitude, longitude, 'gda94')


# Example usage and testing
if __name__ == "__main__":
    # Create converter instance
    converter = GDA2020Converter()
    
    # Test coordinates across Australia
    test_coords = [
        (-31.9505, 115.8605),  # Perth, WA - should be zone 50
        (-34.9285, 138.6007),  # Adelaide, SA - should be zone 54  
        (-37.8136, 144.9631),  # Melbourne, VIC - should be zone 55
        (-33.8688, 151.2093),  # Sydney, NSW - should be zone 56
        (-27.4698, 153.0251),  # Brisbane, QLD - should be zone 56
        (-12.4634, 130.8456),  # Darwin, NT - should be zone 52
        (-42.8821, 147.3272),  # Hobart, TAS - should be zone 55
    ]
    
    print("Individual conversions (GDA2020 only):")
    for lat, lon in test_coords:
        info = converter.get_zone_info(lat, lon)
        if info:
            print(f"Coords: ({lat}, {lon}) -> GDA2020 WKID: {info['gda2020_wkid']}, Zone: {info['utm_zone']}")
            print(f"  Description: {info['description']}")
        else:
            print(f"Coords: ({lat}, {lon}) -> Outside Australia")
        print()
    
    print("\nIndividual conversions (both GDA2020 and GDA94):")
    for lat, lon in test_coords[:3]:  # Just show first 3 for brevity
        info = converter.get_zone_info(lat, lon, include_gda94=True)
        if info:
            print(f"Coords: ({lat}, {lon}) -> Zone: {info['utm_zone']}")
            print(f"  GDA2020 WKID: {info['gda2020_wkid']}")
            print(f"  GDA94 WKID: {info['gda94_wkid']}")
            print(f"  Description: {info['description']}")
        print()
    
    print("\nBatch conversion with both datums:")
    batch_results = converter.batch_convert(test_coords[:3], include_gda94=True)
    for result in batch_results:
        if result['success']:
            info = result['result']
            print(f"{result['input_coordinates']} -> GDA2020: {info['gda2020_wkid']}, GDA94: {info['gda94_wkid']}")
        else:
            print(f"{result['input_coordinates']} -> Error: {result['error']}")
    
    print("\nAll available zones (both datums):")
    all_zones = converter.get_all_zones(include_gda94=True)
    for zone, info in all_zones.items():
        print(f"Zone {zone}: GDA2020 WKID {info['gda2020_wkid']}, GDA94 WKID {info['gda94_wkid']} - {info['description']}")
    
    print("\nTesting individual datum functions:")
    lat, lon = -31.9505, 115.8605  # Perth
    print(f"Perth coords: ({lat}, {lon})")
    print(f"GDA2020 WKID: {get_gda2020_wkid(lat, lon)}")
    print(f"GDA94 WKID: {get_gda94_wkid(lat, lon)}")
