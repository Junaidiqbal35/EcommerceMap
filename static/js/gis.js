(function() {
  'use strict';


  window.gisApp = window.gisApp || {};

  // Configuration constants
  const CONFIG = {
    MAP_CENTER: [-27.47, 153.02],
    MAP_ZOOM: 10,
    SEARCH_RADIUS: 2000,
    DEBOUNCE_DELAY: 500,
    FEATURE_LOAD_PAD: 0.2,
    URLS: {
      ALL_LAYERS: '/all-layers/',
      LAYER_FEATURES: '/layer-preview-features/',
      NEARBY_LAYERS: '/nearby-layers/',
      EXPORT_DXF: '/export-dxf-multi/'
    }
  };


  const state = {
    map: null,
    layers: [],
    activeLayers: {},
    basemaps: {},
    currentBasemap: 'osm',
    selectedCount: 0,
    clickedLocation: null,
    moveHandler: null,
    isMinimized: false,
    visibleFeatures: 0
  };


  function init() {

    checkAuthentication().then(isAuthenticated => {
      if (!isAuthenticated) {
        showLoginModal();
        return;
      }


      initMap();


      loadLayers();


      bindEvents();


      // makePanelDraggable('layerPanel');
    });
  }

  async function checkAuthentication() {
    try {

      const response = await fetch(CONFIG.URLS.ALL_LAYERS);
      return response.ok;
    } catch (error) {
      return false;
    }
  }

  function showLoginModal() {
    const loginModal = document.getElementById('loginModal');
    if (loginModal) {
      loginModal.classList.add('active');
    }
  }

  function initMap() {
    state.map = L.map('map').setView(CONFIG.MAP_CENTER, CONFIG.MAP_ZOOM);

    // Setup all basemaps
    setupBasemaps();

    // Add default basemap
    state.basemaps.osm.addTo(state.map);

    // Add hash for URL updates
    const hash = new L.Hash(state.map);

    // Add geocoder control
    L.Control.geocoder({
      defaultMarkGeocode: false
    }).on('markgeocode', function(e) {
      const bbox = e.geocode.bbox;
      const poly = L.polygon([
        bbox.getSouthEast(),
        bbox.getNorthEast(),
        bbox.getNorthWest(),
        bbox.getSouthWest()
      ]);
      state.map.fitBounds(poly.getBounds());
    }).addTo(state.map);

    // Map click handler for nearby layers
    state.map.on('click', handleMapClick);
  }

  function setupBasemaps() {
    // OpenStreetMap
    state.basemaps.osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 19
    });

    // Terrain/Topographic
    state.basemaps.terrain = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
      attribution: '© Esri',
      maxZoom: 19
    });

    // Dark mode
    state.basemaps.dark = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png', {
      attribution: '© CARTO',
      maxZoom: 19
    });
  }

  function makePanelDraggable(panelId) {
    const panel = document.getElementById(panelId);
    const header = panel.querySelector('.panel-header');
    let isDragging = false;
    let startX, startY, initialX, initialY;

    header.addEventListener('mousedown', (e) => {
      if (e.target.closest('button')) return;
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      const rect = panel.getBoundingClientRect();
      initialX = rect.left;
      initialY = rect.top;
      panel.style.transition = 'none';
    });

    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      panel.style.left = initialX + dx + 'px';
      panel.style.top = initialY + dy + 'px';
      panel.style.right = 'auto';
    });

    document.addEventListener('mouseup', () => {
      isDragging = false;
      panel.style.transition = '';
    });
  }


  async function loadLayers() {
    try {
      const response = await fetch(CONFIG.URLS.ALL_LAYERS);
      if (!response.ok) throw new Error('Failed to load layers');

      state.layers = await response.json();
      renderLayerList();
      updateStats();
    } catch (error) {
      console.error('Error loading layers:', error);
      document.getElementById('layerList').innerHTML =
        '<div style="color: white; text-align: center; padding: 20px; background: rgba(220, 38, 38, 0.2); border-radius: 8px; margin: 10px; border: 1px solid rgba(255, 255, 255, 0.2);">Failed to load layers. Please refresh.</div>';
    }
  }

  function renderLayerList() {
    const container = document.getElementById('layerList');

    if (!state.layers.length) {
      container.innerHTML = '<div style="text-align: center; color: rgba(255, 255, 255, 0.7); padding: 20px;">No layers available</div>';
      return;
    }

    // Group layers by server
    const grouped = {};
    state.layers.forEach(layer => {
      const server = layer.server_name || 'Unknown';
      if (!grouped[server]) grouped[server] = [];
      grouped[server].push(layer);
    });

    let html = '';
    Object.entries(grouped).forEach(([serverName, layers]) => {
      if (layers.length === 0) return;

      html += `<div style="margin-bottom: 20px;">
        <div style="font-size: 12px; font-weight: 600; color: rgba(255, 255, 255, 0.8); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">
          ${serverName} (${layers.length})
        </div>`;

      layers.forEach(layer => {
        const isActive = state.activeLayers[layer.id];
        const typeIcon = getTypeIcon(layer.type);

        html += `
          <div class="layer-item ${isActive ? 'active' : ''}" 
               data-layer-id="${layer.id}"
               title="${layer.name} - ${layer.type} layer from ${layer.server_name}">
            <input type="checkbox" 
                   class="layer-checkbox" 
                   id="layer-${layer.id}"
                   ${isActive ? 'checked' : ''}
                   onclick="event.stopPropagation(); gisApp.toggleLayer(${layer.id})">
            <div class="layer-info">
              <div class="layer-name">${layer.name}</div>
              <div class="layer-meta">
                <span class="layer-type-badge">${typeIcon} ${layer.type}</span>
              </div>
            </div>
            ${layer.centroid_lat && layer.centroid_lng ? 
              `<button class="btn-zoom" onclick="event.stopPropagation(); gisApp.zoomToLayer(${layer.id})" title="Zoom to layer">
                🔍
              </button>` : ''}
          </div>
        `;
      });

      html += '</div>';
    });

    container.innerHTML = html || '<div style="text-align: center; color: rgba(255, 255, 255, 0.7); padding: 20px;">No layers available</div>';
  }

  async function toggleLayer(layerId) {
    const layer = state.layers.find(l => l.id === layerId);
    if (!layer) return;

    const checkbox = document.getElementById(`layer-${layerId}`);
    const layerItem = document.querySelector(`.layer-item[data-layer-id="${layerId}"]`);
    const isChecked = checkbox.checked;

    if (isChecked) {
      layerItem.classList.add('active');
      await addLayerToMap(layer);
      state.selectedCount++;
    } else {
      layerItem.classList.remove('active');
      removeLayerFromMap(layer);
      state.selectedCount--;
    }

    updateDownloadInfo();
    updateStats();
  }

  async function addLayerToMap(layer) {
    try {
      // Store the layer data
      const layerData = {
        layer: layer,
        features: new L.FeatureGroup(),
        loadedBounds: null
      };

      // Add to map first
      layerData.features.addTo(state.map);
      state.activeLayers[layer.id] = layerData;

      // Show loading indicator
      const layerItem = document.querySelector(`.layer-item[data-layer-id="${layer.id}"]`);
      layerItem.classList.add('layer-loading');

      // Load features for current view
      await loadLayerFeatures(layer.id);

      // Remove loading indicator
      layerItem.classList.remove('layer-loading');

      // Setup map move listener for this layer
      if (!state.moveHandler) {
        state.moveHandler = debounce(() => {
          Object.keys(state.activeLayers).forEach(layerId => {
            loadLayerFeatures(layerId);
          });
        }, CONFIG.DEBOUNCE_DELAY);

        state.map.on('moveend', state.moveHandler);
      }

      // If this is a point layer with offset coordinates, add a marker
      if (layer.type === 'point' && layer.offsetX && layer.offsetY &&
          layer.offsetX !== 0 && layer.offsetY !== 0) {
        const marker = L.circleMarker([layer.offsetY, layer.offsetX], {
          radius: 8,
          fillColor: '#ff0000',
          color: '#fff',
          weight: 2,
          opacity: 1,
          fillOpacity: 0.8,
          isReference: true
        });
        marker.bindPopup(`<strong>${layer.name}</strong><br>Reference Point`);
        layerData.features.addLayer(marker);
      }

    } catch (error) {
      console.error('Error adding layer:', error);
      // Uncheck if failed
      document.getElementById(`layer-${layer.id}`).checked = false;
      document.querySelector(`.layer-item[data-layer-id="${layer.id}"]`).classList.remove('active');
      alert(`Failed to load layer: ${layer.name}`);
    }
  }

  function removeLayerFromMap(layer) {
    const layerData = state.activeLayers[layer.id];
    if (layerData) {
      state.map.removeLayer(layerData.features);
      delete state.activeLayers[layer.id];

      // Remove move handler if no layers active
      if (Object.keys(state.activeLayers).length === 0 && state.moveHandler) {
        state.map.off('moveend', state.moveHandler);
        state.moveHandler = null;
      }

      updateVisibleFeatures();
    }
  }

  async function loadLayerFeatures(layerId) {
    const layerData = state.activeLayers[layerId];
    if (!layerData) return;

    const bounds = state.map.getBounds();
    const zoom = state.map.getZoom();


    if (layerData.loadedBounds &&
        layerData.loadedBounds.contains(bounds) &&
        Math.abs(layerData.lastZoom - zoom) < 2) {
      return;
    }


    const expanded = bounds.pad(CONFIG.FEATURE_LOAD_PAD);

    try {
      const params = new URLSearchParams({
        layer_id: layerId,
        minx: expanded.getWest(),
        miny: expanded.getSouth(),
        maxx: expanded.getEast(),
        maxy: expanded.getNorth()
      });

      const response = await fetch(`${CONFIG.URLS.LAYER_FEATURES}?${params}`);
      if (!response.ok) throw new Error('Failed to load features');

      const geojson = await response.json();

      // Clear existing features (except reference point)
      layerData.features.eachLayer(layer => {
        if (!layer.options.isReference) {
          layerData.features.removeLayer(layer);
        }
      });

      // Add new features
      if (geojson.features && geojson.features.length > 0) {
        const newFeatures = L.geoJSON(geojson, {
          style: getLayerStyle(layerData.layer),
          pointToLayer: (feature, latlng) => {
            return L.circleMarker(latlng, {
              radius: 6,
              fillColor: getLayerColor(layerData.layer.type),
              color: '#fff',
              weight: 2,
              opacity: 1,
              fillOpacity: 0.8
            });
          },
          onEachFeature: (feature, leafletLayer) => {
            // Create enhanced popup with download button
            const coords = leafletLayer.getLatLng ? leafletLayer.getLatLng() : null;
            const popupContent = `
              <div class="popup-header">
                <h4 class="popup-title">${feature.properties.layer_name || layerData.layer.name}</h4>
              </div>
              <div class="popup-body">
                <div class="popup-info">
                  <strong>Type:</strong> ${feature.properties.layer_type || layerData.layer.type}<br>
                  <strong>Server:</strong> ${layerData.layer.server_name}<br>
                  ${feature.properties.id ? `<strong>Feature ID:</strong> ${feature.properties.id}<br>` : ''}
                  ${coords ? `<strong>Location:</strong> ${coords.lat.toFixed(5)}, ${coords.lng.toFixed(5)}<br>` : ''}
                </div>
                <div class="popup-actions">
                  <button class="popup-btn popup-btn-primary" onclick="gisApp.downloadSingleFeature(${layerId}, '${coords ? coords.lat + ',' + coords.lng : ''}')">
                    💾 Download
                  </button>
                  ${coords ? `<button class="popup-btn popup-btn-secondary" onclick="gisApp.zoomToFeature(${coords.lat}, ${coords.lng})">
                    🔍 Zoom
                  </button>` : ''}
                </div>
              </div>
            `;
            leafletLayer.bindPopup(popupContent, {
              maxWidth: 300,
              className: 'custom-popup'
            });

            // Tooltip for hover
            leafletLayer.bindTooltip(layerData.layer.name, {
              permanent: false,
              direction: 'top',
              offset: [0, -10]
            });
          }
        });

        newFeatures.eachLayer(layer => {
          layerData.features.addLayer(layer);
        });

        // Update loaded bounds
        layerData.loadedBounds = expanded;
        layerData.lastZoom = zoom;

        // Update feature count in UI
        updateFeatureCount(layerId, geojson.features.length);

        // Update total visible features
        updateVisibleFeatures();

        // Check if any active layers have features
        checkForNoFeatures();
      } else {
        updateFeatureCount(layerId, 0);
        updateVisibleFeatures();
        checkForNoFeatures();
      }

    } catch (error) {
      console.error('Error loading features:', error);
    }
  }

  function toggleMinimize() {
    const panel = document.getElementById('layerPanel');
    const icon = document.getElementById('minimizeIcon');

    state.isMinimized = !state.isMinimized;

    if (state.isMinimized) {
      panel.classList.add('minimized');
      icon.textContent = '+';
    } else {
      panel.classList.remove('minimized');
      icon.textContent = '−';
    }
  }

  function updateStats() {
    // Simplified - only update layer count in header
    const activeCount = Object.keys(state.activeLayers).length;
    const layerCount = document.getElementById('layerCount');
    if (activeCount > 0) {
      layerCount.textContent = `(${activeCount} active)`;
    } else {
      layerCount.textContent = '';
    }
  }

  function updateVisibleFeatures() {
    let total = 0;
    Object.values(state.activeLayers).forEach(layerData => {
      if (layerData.features) {
        layerData.features.eachLayer(() => total++);
      }
    });
    state.visibleFeatures = total;
    updateStats();
  }

  function updateFeatureCount(layerId, count) {
    const layerItem = document.querySelector(`.layer-item[data-layer-id="${layerId}"]`);
    if (!layerItem) return;

    // Remove existing count
    const existingCount = layerItem.querySelector('.feature-count');
    if (existingCount) {
      existingCount.remove();
    }

    // Add new count
    if (count > 0) {
      const countSpan = document.createElement('span');
      countSpan.className = 'feature-count';
      countSpan.textContent = count > 999 ? '999+' : count;
      layerItem.querySelector('.layer-meta').appendChild(countSpan);
    }
  }

  function checkForNoFeatures() {
    let totalFeatures = 0;
    Object.values(state.activeLayers).forEach(layerData => {
      if (layerData.features) {
        layerData.features.eachLayer(() => totalFeatures++);
      }
    });

    const message = document.getElementById('noFeaturesMessage');
    if (Object.keys(state.activeLayers).length > 0 && totalFeatures === 0) {
      message.style.display = 'block';
      setTimeout(() => {
        message.style.display = 'none';
      }, 5000);
    } else {
      message.style.display = 'none';
    }
  }

  function updateDownloadInfo() {
    const countEl = document.querySelector('.export-count');
    const costEl = document.getElementById('exportCost');
    const btn = document.getElementById('downloadBtn');
    const fab = document.getElementById('exportFab');

    if (state.selectedCount > 0) {
      if (countEl) countEl.textContent = state.selectedCount;
      if (costEl) costEl.innerHTML = `Cost: <strong>${state.selectedCount} connects</strong>`;
      if (btn) btn.disabled = false;
      if (fab) fab.style.display = 'flex';
    } else {
      if (countEl) countEl.textContent = '0';
      if (costEl) costEl.innerHTML = 'Cost: <strong>0 connects</strong>';
      if (btn) btn.disabled = true;
      if (fab) fab.style.display = 'none';
    }
  }

  function toggleExportPanel() {
    const modal = document.getElementById('exportModal');
    if (modal) {
      modal.classList.toggle('active');
    }
  }

  function zoomToLayer(layerId) {
    const layer = state.layers.find(l => l.id === layerId);
    if (!layer || !layer.centroid_lat || !layer.centroid_lng) return;

    // Smooth zoom animation
    state.map.flyTo([layer.centroid_lat, layer.centroid_lng], 15, {
      duration: 1.5
    });

    // Activate layer if not already active
    if (!state.activeLayers[layerId]) {
      const checkbox = document.getElementById(`layer-${layerId}`);
      if (checkbox && !checkbox.checked) {
        checkbox.checked = true;
        toggleLayer(layerId);
      }
    }
  }

  function zoomToFeature(lat, lng) {
    state.map.flyTo([lat, lng], 18, {
      duration: 1
    });
  }

  function refreshLayers() {
    // Show loading
    document.getElementById('layerList').innerHTML = '<div class="spinner"></div>';
    loadLayers();
  }



  async function handleMapClick(e) {
    state.clickedLocation = e.latlng;
    await showNearbyLayers(e.latlng.lat, e.latlng.lng);
  }

  async function showNearbyLayers(lat, lng) {
    const sidebar = document.getElementById('sidebar');
    const list = document.getElementById('nearbyList');

    sidebar.classList.add('active');
    list.innerHTML = '<div class="spinner"></div>';

    try {
      // 2km search radius
      const response = await fetch(`${CONFIG.URLS.NEARBY_LAYERS}?lat=${lat}&lng=${lng}&dist=${CONFIG.SEARCH_RADIUS}`);
      const layers = await response.json();

      if (!layers || !layers.length) {
        list.innerHTML = `
          <div style="text-align: center; color: #718096; padding: 20px;">
            <div style="font-size: 48px; margin-bottom: 10px;">📍</div>
            <div>No layers found within 2km</div>
            <div style="font-size: 12px; margin-top: 10px;">Try clicking in a different area</div>
          </div>
        `;
        return;
      }

      let html = '';
      layers.forEach(layer => {
        const typeIcon = getTypeIcon(layer.type);
        const distance = layer.distance_m ? Math.round(layer.distance_m) : 0;
        html += `
          <div class="nearby-layer-item">
            <label>
              <input type="checkbox" value="${layer.id}" checked>
              <div class="nearby-info">
                <div class="nearby-name">${typeIcon} ${layer.name}</div>
                <div class="nearby-distance">
                  ${layer.type} • ${distance}m away • ${layer.server_name}
                </div>
              </div>
            </label>
          </div>
        `;
      });

      list.innerHTML = html;

    } catch (error) {
      console.error('Failed to load nearby layers:', error);
      list.innerHTML = '<div style="color: #ef4444; text-align: center;">Failed to load nearby layers</div>';
    }
  }

  function closeSidebar() {
    document.getElementById('sidebar').classList.remove('active');
  }


  async function exportLayers() {
    const format = document.getElementById('exportFormat').value;
    const selectedIds = Object.keys(state.activeLayers);

    if (!selectedIds.length) {
      alert('Please select at least one layer to export');
      return;
    }

    const btn = document.getElementById('downloadBtn');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span><span>Exporting...</span>';

    try {
      if (format === 'dxf') {
        await exportAsDXF(selectedIds);
      } else {
        exportAsGeoJSON(selectedIds);
      }
    } catch (error) {
      console.error('Export error:', error);
      alert('Export failed: ' + error.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }

  async function exportAsDXF(layerIds) {
    const formData = new FormData();
    layerIds.forEach(id => formData.append('layer_ids[]', id));

    const bounds = state.map.getBounds();
    formData.append('minx', bounds.getWest());
    formData.append('miny', bounds.getSouth());
    formData.append('maxx', bounds.getEast());
    formData.append('maxy', bounds.getNorth());

    const response = await fetch(CONFIG.URLS.EXPORT_DXF, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Export failed');
    }

    const blob = await response.blob();
    downloadFile(blob, `gis_export_${new Date().toISOString().slice(0, 10)}.dxf`);
  }

  function exportAsGeoJSON(layerIds) {
    const features = [];

    layerIds.forEach(id => {
      const layerData = state.activeLayers[id];
      if (layerData && layerData.features) {
        layerData.features.eachLayer(layer => {
          if (layer.feature) {
            features.push(layer.feature);
          } else if (layer.toGeoJSON) {
            // Convert to GeoJSON if it's a regular layer
            const geoJson = layer.toGeoJSON();
            if (geoJson) {
              features.push(geoJson);
            }
          }
        });
      }
    });

    const geojson = {
      type: 'FeatureCollection',
      features: features
    };

    const blob = new Blob([JSON.stringify(geojson, null, 2)], {type: 'application/json'});
    downloadFile(blob, `gis_export_${new Date().toISOString().slice(0, 10)}.geojson`);
  }

  async function downloadNearbyLayers(e) {
    e.preventDefault();

    const checkboxes = document.querySelectorAll('#nearbyList input:checked');
    if (!checkboxes.length) {
      alert('Please select at least one layer');
      return;
    }

    const btn = e.target.querySelector('button[type="submit"]');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span><span>Downloading...</span>';

    try {
      const formData = new FormData();
      checkboxes.forEach(cb => formData.append('layer_ids[]', cb.value));

      if (state.clickedLocation) {
        formData.append('lat', state.clickedLocation.lat);
        formData.append('lng', state.clickedLocation.lng);
      }

      // 2km area around clicked point
      const offset = 0.02;
      formData.append('minx', state.clickedLocation.lng - offset);
      formData.append('miny', state.clickedLocation.lat - offset);
      formData.append('maxx', state.clickedLocation.lng + offset);
      formData.append('maxy', state.clickedLocation.lat + offset);

      const response = await fetch(CONFIG.URLS.EXPORT_DXF, {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Download failed');
      }

      const blob = await response.blob();
      downloadFile(blob, `nearby_layers_${new Date().toISOString().slice(0, 10)}.dxf`);

      closeSidebar();

    } catch (error) {
      alert('Download failed: ' + error.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }

  async function downloadSingleFeature(layerId, coords) {
    try {
      const layer = state.layers.find(l => l.id === layerId);
      if (!layer) return;

      // Parse coordinates
      const [lat, lng] = coords.split(',').map(parseFloat);
      const offset = 0.001; // ~100m

      const formData = new FormData();
      formData.append('layer_ids[]', layerId);
      formData.append('minx', lng - offset);
      formData.append('miny', lat - offset);
      formData.append('maxx', lng + offset);
      formData.append('maxy', lat + offset);

      const response = await fetch(CONFIG.URLS.EXPORT_DXF, {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Download failed');
      }

      const blob = await response.blob();
      downloadFile(blob, `${layer.name}_feature.dxf`);

    } catch (error) {
      alert('Download failed: ' + error.message);
    }
  }



  function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }

  function downloadFile(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function getTypeIcon(type) {
    const icons = {
      'point': '📍',
      'polyline': '📏',
      'polygon': '🏗️'
    };
    return icons[type] || '📄';
  }

  function getLayerStyle(layer) {
    const colors = {
      polygon: '#3388ff',
      polyline: '#ff7800',
      point: '#51bbd6'
    };

    return {
      color: colors[layer.type] || '#3388ff',
      weight: layer.type === 'polygon' ? 2 : 3,
      opacity: 0.8,
      fillOpacity: layer.type === 'polygon' ? 0.3 : 0.7
    };
  }

  function getLayerColor(type) {
    const colors = {
      'point': '#e74c3c',
      'polyline': '#f39c12',
      'polygon': '#3498db'
    };
    return colors[type] || '#95a5a6';
  }

  function switchBasemap(name) {
    if (state.basemaps[state.currentBasemap]) {
      state.map.removeLayer(state.basemaps[state.currentBasemap]);
    }

    state.currentBasemap = name;
    if (state.basemaps[name]) {
      state.basemaps[name].addTo(state.map);
    }
  }


  function bindEvents() {
    // Basemap switcher
    document.querySelectorAll('input[name="basemap"]').forEach(radio => {
      radio.addEventListener('change', (e) => {
        if (e.target.checked) {
          switchBasemap(e.target.value);
        }
      });
    });

    // Nearby layers form
    const nearbyForm = document.getElementById('nearbyForm');
    if (nearbyForm) {
      nearbyForm.addEventListener('submit', downloadNearbyLayers);
    }

    // Basemap control hover
    const basemapControl = document.querySelector('.basemap-control');
    const basemapOptions = document.querySelector('.basemap-options');

    if (basemapControl && basemapOptions) {
      basemapControl.addEventListener('mouseenter', () => {
        basemapOptions.classList.add('active');
      });

      basemapControl.addEventListener('mouseleave', () => {
        basemapOptions.classList.remove('active');
      });
    }

    // Layer item click handler
    const layerList = document.getElementById('layerList');
    if (layerList) {
      layerList.addEventListener('click', (e) => {
        const layerItem = e.target.closest('.layer-item');
        if (layerItem && !e.target.closest('input') && !e.target.closest('button')) {
          const checkbox = layerItem.querySelector('.layer-checkbox');
          if (checkbox) {
            checkbox.click();
          }
        }
      });
    }

    // Export modal close on outside click
    const exportModal = document.getElementById('exportModal');
    if (exportModal) {
      exportModal.addEventListener('click', (e) => {
        if (e.target === exportModal) {
          toggleExportPanel();
        }
      });
    }
  }


  // Expose public methods
  window.gisApp = {
    init: init,
    toggleLayer: toggleLayer,
    zoomToLayer: zoomToLayer,
    exportLayers: exportLayers,
    refreshLayers: refreshLayers,
    closeSidebar: closeSidebar,
    toggleMinimize: toggleMinimize,
    toggleExportPanel: toggleExportPanel,
    downloadSingleFeature: downloadSingleFeature,
    zoomToFeature: zoomToFeature
  };

})();