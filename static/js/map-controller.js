/* Map Controller - Fixed Version with Single Preferred Layer Auto-Select */
/* global L, htmx */

const MapController = {
    map: null,
    baseLayers: {},
    previewLayers: {},
    activeLayers: new Set(),
    layerStatus: new Map(),
    pendingRequests: new Map(),
    config: {},
    clickMarker: null,
    preferredLayerIds: [],

    init(config) {
        this.config = config;
        console.log('MapController initializing with config:', config);
        this.initMap();
        this.initEventListeners();

        // Load preferred layers after a short delay to ensure DOM is ready
        setTimeout(() => this.loadPreferredLayers(), 800);
    },

    initMap() {
        // Initialize map centered on Brisbane/Gold Coast area
        this.map = L.map('map', {
            center: [-27.9, 153.2],
            zoom: 11,
            preferCanvas: true
        });

        // Add base layers
        this.baseLayers = {
            'osm': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: 'OpenStreetMap',
                maxZoom: 19
            }),
            'satellite': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: 'Esri',
                maxZoom: 19
            }),
            'dark': L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                attribution: 'CARTO',
                maxZoom: 19
            })
        };

        this.baseLayers.osm.addTo(this.map);
        L.control.scale().addTo(this.map);

        // Map events
        this.map.on('moveend', () => this.onMapMove());
        this.map.on('zoomend', () => this.onMapZoom());

        // Add click handler for nearby layers
        this.map.on('click', (e) => {
            console.log('Map clicked at:', e.latlng);
            this.handleMapClick(e);
        });
    },

    initEventListeners() {
        // Listen for HTMX events
        document.body.addEventListener('htmx:afterSwap', (evt) => {
            console.log('HTMX swap completed');

            // Reinitialize Alpine.js components if needed
            if (window.Alpine && evt.detail.target.querySelector('[x-data]')) {
                window.Alpine.initTree(evt.detail.target);
            }

            // Re-apply preferred layer styling after layer list is swapped
            if (evt.detail.target.id === 'layer-list' || evt.detail.target.closest('#layer-list')) {
                setTimeout(() => this.highlightPreferredLayer(), 300);
            }

            // Open sidebar when nearby content loads
            if (evt.detail.target.id === 'nearbyContent') {
                this.openNearbySidebar();
            }
        });

        // Listen for filter button clicks
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('filter-btn')) {
                const filterType = e.target.dataset.filter || 'all';
                this.applyFilter(filterType, e.target);
            }
        });
    },

    // Load and activate ONE preferred layer (the most used one)
    loadPreferredLayers() {
        // Check if preferredLayerIds was set by the template
        if (window.preferredLayerIds && Array.isArray(window.preferredLayerIds)) {
            this.preferredLayerIds = window.preferredLayerIds;
            console.log('Loaded preferred layer IDs:', this.preferredLayerIds);

            // FIXED: Only activate ONE layer (the first one = most downloaded)
            this.activateSinglePreferredLayer();
        }
    },

    // FIXED: Activate only ONE preferred layer (highest download count)
    activateSinglePreferredLayer() {
        if (!this.preferredLayerIds || this.preferredLayerIds.length === 0) {
            return;
        }

        // Get only the FIRST preferred layer (sorted by download_count DESC from backend)
        const topLayerId = this.preferredLayerIds[0];
        console.log('Auto-activating single preferred layer:', topLayerId);

        const checkbox = document.getElementById(`layer-${topLayerId}`);
        if (checkbox) {
            // Check the checkbox
            if (!checkbox.checked) {
                checkbox.checked = true;
            }
            // Activate the layer
            if (!this.activeLayers.has(topLayerId)) {
                this.activateLayer(topLayerId);
            }

            // Scroll to and highlight the layer
            const layerItem = document.querySelector(`[data-layer-id="${topLayerId}"]`);
            if (layerItem) {
                layerItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }

        this.updateActiveCount();
        this.showToast('Your most-used layer loaded', 'success');
    },

    // Highlight preferred layers in the list (without activating them)
    highlightPreferredLayer() {
        if (!this.preferredLayerIds || this.preferredLayerIds.length === 0) {
            return;
        }

        // Only ensure the first (active) preferred layer checkbox stays checked
        const topLayerId = this.preferredLayerIds[0];
        const checkbox = document.getElementById(`layer-${topLayerId}`);
        if (checkbox && this.activeLayers.has(topLayerId) && !checkbox.checked) {
            checkbox.checked = true;
        }
    },

    handleMapClick(e) {
        const lat = e.latlng.lat;
        const lng = e.latlng.lng;

        console.log(`Getting nearby layers for: ${lat}, ${lng}`);

        // Remove previous click marker
        if (this.clickMarker) {
            this.map.removeLayer(this.clickMarker);
        }

        // Add new click marker
        this.clickMarker = L.circleMarker([lat, lng], {
            radius: 8,
            fillColor: '#ff7800',
            color: '#fff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.8
        }).addTo(this.map);

        // Update form values
        const form = document.getElementById('mapClickForm');
        if (form) {
            document.getElementById('clickLat').value = lat;
            document.getElementById('clickLng').value = lng;

            // Get selected layers
            const selectedLayerIds = Array.from(this.activeLayers).join(',');
            document.getElementById('selectedLayers').value = selectedLayerIds;

            console.log('Triggering HTMX form submit for nearby layers');

            // Trigger HTMX request
            htmx.trigger(form, 'submit');
        } else {
            console.error('mapClickForm not found');
        }
    },

    onMapMove() {
        this.refreshActivePreviews();
    },

    onMapZoom() {
        const zoom = this.map.getZoom();
        console.log('Map zoom:', zoom);

        if (zoom < 12 && this.activeLayers.size > 0) {
            this.showToast('Zoom in closer to see layer features', 'info');
        }
        this.refreshActivePreviews();
    },

    refreshActivePreviews() {
        clearTimeout(this.refreshTimeout);
        this.refreshTimeout = setTimeout(() => {
            this.activeLayers.forEach(layerId => {
                this.loadLayerPreview(layerId);
            });
        }, 500);
    },

    toggleLayer(layerId, checkbox) {
        console.log(`Toggling layer ${layerId}: ${checkbox.checked}`);

        if (checkbox.checked) {
            this.activateLayer(layerId);
        } else {
            this.deactivateLayer(layerId);
        }
        this.updateActiveCount();
    },

    activateLayer(layerId) {
        console.log(`Activating layer ${layerId}`);
        this.activeLayers.add(layerId);

        const layerItem = document.querySelector(`[data-layer-id="${layerId}"]`);
        if (layerItem) {
            layerItem.classList.add('layer-active');
        }

        this.loadLayerPreview(layerId);
    },

    deactivateLayer(layerId) {
        console.log(`Deactivating layer ${layerId}`);
        this.activeLayers.delete(layerId);

        if (this.previewLayers[layerId]) {
            this.map.removeLayer(this.previewLayers[layerId]);
            delete this.previewLayers[layerId];
        }

        if (this.pendingRequests.has(layerId)) {
            const controller = this.pendingRequests.get(layerId);
            controller.abort();
            this.pendingRequests.delete(layerId);
        }

        const layerItem = document.querySelector(`[data-layer-id="${layerId}"]`);
        if (layerItem) {
            layerItem.classList.remove('layer-active');
        }
    },

    async loadLayerPreview(layerId) {
        const bounds = this.map.getBounds();
        const zoom = this.map.getZoom();

        // Skip if zoomed out too far
        if (zoom < 10) {
            console.log(`Zoom ${zoom} too low, skipping preview for layer ${layerId}`);
            return;
        }

        // Cancel any pending request for this layer
        if (this.pendingRequests.has(layerId)) {
            this.pendingRequests.get(layerId).abort();
        }

        const controller = new AbortController();
        this.pendingRequests.set(layerId, controller);

        this.updateLayerStatus(layerId, 'loading');

        try {
            const params = new URLSearchParams({
                layer_id: layerId,
                minx: bounds.getWest(),
                miny: bounds.getSouth(),
                maxx: bounds.getEast(),
                maxy: bounds.getNorth()
            });

            const response = await fetch(`${this.config.previewUrl}?${params}`, {
                signal: controller.signal
            });

            if (!response.ok) throw new Error('Failed to fetch preview');

            const geojson = await response.json();

            // Remove existing preview
            if (this.previewLayers[layerId]) {
                this.map.removeLayer(this.previewLayers[layerId]);
            }

            // Add new preview
            if (geojson.features && geojson.features.length > 0) {
                const layer = L.geoJSON(geojson, {
                    style: this.getLayerStyle(geojson.features[0]?.properties?.layer_type),
                    pointToLayer: (feature, latlng) => {
                        return L.circleMarker(latlng, {
                            radius: 6,
                            fillColor: this.getLayerColor(feature.properties?.layer_type),
                            color: '#fff',
                            weight: 2,
                            fillOpacity: 0.8
                        });
                    },
                    onEachFeature: (feature, layer) => {
                        if (feature.properties) {
                            let popup = `<strong>${feature.properties.layer_name || 'Feature'}</strong>`;
                            if (feature.properties.layer_type) {
                                popup += `<br>Type: ${feature.properties.layer_type}`;
                            }
                            layer.bindPopup(popup);
                        }
                    }
                });

                layer.addTo(this.map);
                this.previewLayers[layerId] = layer;
                this.updateLayerStatus(layerId, 'loaded', geojson.features.length);
            } else {
                this.updateLayerStatus(layerId, 'empty');
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log(`Request for layer ${layerId} was aborted`);
            } else {
                console.error(`Error loading layer ${layerId}:`, error);
                this.updateLayerStatus(layerId, 'error');
            }
        } finally {
            this.pendingRequests.delete(layerId);
        }
    },

    updateLayerStatus(layerId, status, featureCount = 0) {
        this.layerStatus.set(layerId, { status, featureCount });

        const layerItem = document.querySelector(`[data-layer-id="${layerId}"]`);
        if (!layerItem) return;

        // Remove old status classes
        layerItem.classList.remove('loading', 'error', 'empty');

        // Update status indicator
        let statusEl = layerItem.querySelector('.layer-status');
        if (!statusEl) {
            statusEl = document.createElement('span');
            statusEl.className = 'layer-status';
            layerItem.appendChild(statusEl);
        }

        switch (status) {
            case 'loading':
                layerItem.classList.add('loading');
                statusEl.innerHTML = '<span class="spinner-sm"></span>';
                break;
            case 'loaded':
                statusEl.textContent = featureCount > 0 ? `${featureCount}` : '';
                break;
            case 'empty':
                layerItem.classList.add('empty');
                statusEl.textContent = '0';
                break;
            case 'error':
                layerItem.classList.add('error');
                statusEl.textContent = '⚠';
                break;
        }
    },

    getLayerStyle(type) {
        const styles = {
            polygon: { color: '#3388ff', weight: 2, fillOpacity: 0.3 },
            polyline: { color: '#ff7800', weight: 3, fillOpacity: 0 },
            point: { color: '#e74c3c', weight: 2, fillOpacity: 0.8 }
        };
        return styles[type] || styles.polygon;
    },

    getLayerColor(type) {
        const colors = {
            point: '#e74c3c',
            polyline: '#ff7800',
            polygon: '#3388ff'
        };
        return colors[type] || '#3388ff';
    },

    zoomToLayer(layerId, lat, lng) {
        if (lat && lng) {
            this.map.flyTo([lat, lng], 15, { duration: 1 });
        }
    },

    updateActiveCount() {
        const count = this.activeLayers.size;
        const countEl = document.getElementById('activeLayerCount');
        const fab = document.getElementById('exportFab');

        if (countEl) {
            countEl.textContent = count;
        }

        if (fab) {
            fab.style.display = count > 0 ? 'flex' : 'none';
        }
    },

    showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer') || this.createToastContainer();

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${type === 'success' ? '✓' : type === 'error' ? '✗' : type === 'warning' ? '⚠' : 'ℹ'}</span>
            <span class="toast-message">${message}</span>
        `;

        container.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        // Remove after delay
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    },

    createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container';
        document.body.appendChild(container);
        return container;
    },

    applyFilter(filterType, button) {
        console.log('Applying filter:', filterType);

        // Update button states
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        if (button) {
            button.classList.add('active');
        }

        // Update search with filter
        const searchInput = document.getElementById('layerSearch');
        if (searchInput) {
            const currentUrl = searchInput.getAttribute('hx-get');
            const url = new URL(currentUrl, window.location.origin);
            url.searchParams.set('filter', filterType);
            searchInput.setAttribute('hx-get', url.pathname + url.search);

            // Trigger search
            htmx.trigger(searchInput, 'keyup');
        }
    },

    refreshLayers() {
        console.log('Refreshing all active layers');
        this.refreshActivePreviews();
        this.showToast('Refreshing layers...', 'info');
    },

    changeBasemap(mapType) {
        Object.values(this.baseLayers).forEach(layer => {
            this.map.removeLayer(layer);
        });

        if (this.baseLayers[mapType]) {
            this.baseLayers[mapType].addTo(this.map);
            this.showToast(`Switched to ${mapType} map`, 'success');
        }
    },

    toggleBasemapMenu() {
        const menu = document.getElementById('basemapOptions');
        if (menu) {
            menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
        }
    },

    // Nearby layers functions
    openNearbySidebar() {
        console.log('Opening nearby sidebar');
        const sidebar = document.getElementById('nearbySidebar');
        if (sidebar) {
            sidebar.classList.add('open');
        }
    },

    closeNearbySidebar() {
        console.log('Closing nearby sidebar');
        const sidebar = document.getElementById('nearbySidebar');
        if (sidebar) {
            sidebar.classList.remove('open');
        }

        // Remove click marker
        if (this.clickMarker) {
            this.map.removeLayer(this.clickMarker);
            this.clickMarker = null;
        }
    },

    // Download functions
    async downloadArea(layerId, lat, lng) {
        const bounds = this.map.getBounds();
        const selectedLayers = layerId ? [layerId] : Array.from(this.activeLayers);

        if (selectedLayers.length === 0) {
            this.showToast('Please select layers to download', 'warning');
            return;
        }

        this.showToast('Preparing download...', 'info');

        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', this.config.csrfToken);
        selectedLayers.forEach(id => formData.append('layer_ids[]', id));
        formData.append('minx', bounds.getWest());
        formData.append('miny', bounds.getSouth());
        formData.append('maxx', bounds.getEast());
        formData.append('maxy', bounds.getNorth());
        formData.append('lat', lat || bounds.getCenter().lat);
        formData.append('lng', lng || bounds.getCenter().lng);

        try {
            const response = await fetch(this.config.exportUrl, {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                const contentType = response.headers.get('content-type');

                if (contentType && contentType.includes('application/dxf')) {
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `layers_export_${new Date().getTime()}.dxf`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);

                    this.showToast('Download started successfully!', 'success');
                } else {
                    const data = await response.json();
                    const errorMsg = data.error || 'Export failed';
                    this.showToast(errorMsg, 'error');

                    if (data.details) {
                        console.error('Export error details:', data.details);
                    }
                }
            } else {
                this.showToast('Export request failed', 'error');
            }
        } catch (error) {
            console.error('Download error:', error);
            this.showToast('Download failed. Please try again.', 'error');
        }
    },

    async downloadNearbyLayers() {
        const form = document.getElementById('nearbyDownloadForm');
        if (!form) {
            console.error('Nearby download form not found');
            return;
        }

        const checkedBoxes = form.querySelectorAll('input[name="layer_ids[]"]:checked');
        if (checkedBoxes.length === 0) {
            this.showToast('Please select layers to download', 'warning');
            return;
        }

        this.showToast(`Downloading ${checkedBoxes.length} layers...`, 'info');

        const formData = new FormData(form);
        const bounds = this.map.getBounds();
        formData.append('minx', bounds.getWest());
        formData.append('miny', bounds.getSouth());
        formData.append('maxx', bounds.getEast());
        formData.append('maxy', bounds.getNorth());

        try {
            const response = await fetch(this.config.exportUrl, {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                const contentType = response.headers.get('content-type');

                if (contentType && contentType.includes('application/dxf')) {
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `nearby_layers_${new Date().getTime()}.dxf`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);

                    this.showToast('Download started successfully!', 'success');

                    // Close sidebar after successful download
                    setTimeout(() => this.closeNearbySidebar(), 2000);
                } else {
                    const data = await response.json();
                    this.showToast(data.error || 'Export failed', 'error');
                }
            }
        } catch (error) {
            console.error('Download error:', error);
            this.showToast('Download failed', 'error');
        }
    }
};

// Global function bindings
window.MapController = MapController;
window.toggleLayer = (layerId, checkbox) => MapController.toggleLayer(layerId, checkbox);
window.zoomToLayer = (layerId, lat, lng) => MapController.zoomToLayer(layerId, lat, lng);
window.downloadArea = (layerId, lat, lng) => MapController.downloadArea(layerId, lat, lng);
window.downloadNearbyLayers = () => MapController.downloadNearbyLayers();
window.updateNearbyCount = () => {
    const form = document.getElementById('nearbyDownloadForm');
    if (form) {
        const checked = form.querySelectorAll('input[name="layer_ids[]"]:checked').length;
        const countEl = document.getElementById('nearbyCount');
        if (countEl) {
            countEl.textContent = checked > 0 ? `(${checked})` : '';
        }
    }
};