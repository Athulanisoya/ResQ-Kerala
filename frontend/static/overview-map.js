(() => {
  'use strict';
  const COLOURS = { RED: '#d98679', ORANGE: '#e8b879', YELLOW: '#f2dc8b', GREEN: '#b8d0b0' };
  const LABELS = { RED: 'Red alert', ORANGE: 'Orange alert', YELLOW: 'Yellow alert', GREEN: 'No active alert' };
  const RANK = { RED: 3, ORANGE: 2, YELLOW: 1, GREEN: 0 };
  const LOCALITY_ZOOM = 9;
  let active = null;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function coordinates(row) {
    return Number.isFinite(row.latitude) && Number.isFinite(row.longitude)
      && Math.abs(row.latitude) <= 90 && Math.abs(row.longitude) <= 180;
  }
  function distance(origin, row) {
    if (!origin || !coordinates(row)) return Infinity;
    const radians = value => value * Math.PI / 180;
    const a = Math.sin(radians(row.latitude - origin.latitude) / 2) ** 2
      + Math.cos(radians(origin.latitude)) * Math.cos(radians(row.latitude))
      * Math.sin(radians(row.longitude - origin.longitude) / 2) ** 2;
    return 6371.0088 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, a))));
  }
  function time(value) {
    if (!value || !Number.isFinite(Date.parse(value))) return 'Unknown';
    return new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' }).format(new Date(value)) + ' IST';
  }
  function badge(level) {
    const node = element('span', 'map-status-badge');
    node.append(element('i', 'map-dot map-level-' + (COLOURS[level] ? level.toLowerCase() : 'unknown')));
    node.append(document.createTextNode(LABELS[level] || 'Unknown'));
    return node;
  }
  function link(label, href, primary = false) {
    const node = element('a', 'button ' + (primary ? 'button-primary' : 'button-secondary'), label);
    node.href = href;
    node.setAttribute('hx-get', href);
    node.setAttribute('hx-target', '#main-content');
    node.setAttribute('hx-push-url', 'true');
    return node;
  }
  function process(node) { if (window.htmx) window.htmx.process(node); }

  class OverviewMap {
    constructor(root) {
      this.root = root;
      this.role = root.dataset.userRole;
      this.canvas = root.querySelector('[data-map-canvas]');
      this.panel = root.querySelector('[data-map-details]');
      this.status = root.querySelector('[data-map-status]');
      this.districtSelect = root.querySelector('[data-map-district]');
      this.localitySelect = root.querySelector('[data-map-locality]');
      this.refreshButton = root.querySelector('[data-map-refresh]');
      this.controller = new AbortController();
      this.localityMarkers = new Map();
      this.shelterMarkers = new Map();
      this.districtLayers = new Map();
      this.selectedDistrict = '';
      this.selectedLocality = '';
      this.selectedShelter = null;
      this.origin = null;
      this.data = null;
      this.stale = false;
      this.destroyed = false;
      this.map = L.map(this.canvas, { scrollWheelZoom: false, minZoom: 6, maxZoom: 15, zoomControl: true, attributionControl: true });
      this.map.setView([10.5, 76.1], 7);
      this.map.attributionControl.setPrefix('<a href="https://leafletjs.com" rel="noopener noreferrer" target="_blank">Leaflet</a>');
      this.localityGroup = L.layerGroup();
      this.shelterGroup = L.layerGroup().addTo(this.map);
      this.map.on('zoomend', () => this.updateZoom());
      this.map.on('popupopen', event => process(event.popup.getElement()));
      this.districtSelect.addEventListener('change', () => this.chooseDistrict(this.districtSelect.value));
      this.localitySelect.addEventListener('change', () => this.chooseLocality(this.localitySelect.value));
      this.refreshButton.addEventListener('click', () => this.refresh());
      root.querySelector('[data-map-reset]').addEventListener('click', () => this.chooseDistrict(''));
      root.querySelector('[data-map-locate]').addEventListener('click', () => this.locate());
      this.onVisibility = () => { if (!document.hidden) this.refresh(); };
      document.addEventListener('visibilitychange', this.onVisibility);
      this.timer = window.setInterval(() => { if (!document.hidden) this.refresh(); }, 30000);
      this.resizeObserver = new ResizeObserver(() => this.map.invalidateSize({ pan: false }));
      this.resizeObserver.observe(this.canvas);
      this.refresh();
    }

    async read(path) {
      let token;
      try { token = sessionStorage.getItem('resq-week1-session'); } catch { /* The normal sign-in flow explains storage requirements. */ }
      const response = await fetch(path, {
        headers: token ? { Authorization: 'Bearer ' + token } : {}, cache: 'no-store',
        credentials: 'same-origin', redirect: 'error', signal: this.controller.signal,
      });
      if (!response.ok) throw new Error(response.status === 401 ? 'session' : 'unavailable');
      return response.json();
    }

    async refresh() {
      if (this.loading || this.destroyed) return;
      this.loading = true;
      this.refreshButton.disabled = true;
      try {
        const [data, boundary] = await Promise.all([
          this.read('/api/overview/map'), this.boundary ? Promise.resolve(this.boundary) : this.read('/api/overview/district-boundaries'),
        ]);
        if (this.destroyed) return;
        if (!Array.isArray(data.districts) || data.districts.length !== 14 || !Array.isArray(data.localities)
          || !Array.isArray(data.shelters) || boundary.type !== 'FeatureCollection' || boundary.features.length !== 14) throw new Error('unavailable');
        this.data = data;
        this.stale = false;
        this.root.classList.remove('overview-map-unavailable');
        this.boundary = boundary;
        if (!this.geojson) this.drawBoundaries();
        this.paint();
        this.selectors();
        this.details();
        this.status.textContent = 'Map checked ' + time(data.generated_at) + ' · refreshes every 30 seconds while visible.';
        this.attribution(data.attribution);
      } catch (error) {
        if (this.destroyed || error.name === 'AbortError') return;
        this.stale = true;
        this.root.classList.add('overview-map-unavailable');
        this.status.textContent = error.message === 'session' ? 'Map unavailable. Sign in again to refresh your session.'
          : 'Map updates unavailable.' + (this.data ? ' Last successful check: ' + time(this.data.generated_at) + '.' : ' Alert colours are unknown.');
        this.panel.replaceChildren(element('p', 'map-unavailable-note', 'Current alert and shelter data could not be checked. Use Refresh to retry; do not treat the retained map as current availability.'));
        this.districtSelect.disabled = true;
        this.localitySelect.disabled = true;
        this.paintUnknown();
      } finally {
        this.loading = false;
        if (!this.destroyed) this.refreshButton.disabled = false;
      }
    }

    drawBoundaries() {
      this.geojson = L.geoJSON(this.boundary, {
        style: { color: '#78958a', weight: 1.4, fillColor: '#c7cec8', fillOpacity: .8 },
        onEachFeature: (feature, layer) => {
          this.districtLayers.set(feature.properties.id, layer);
          layer.bindTooltip(element('span', '', feature.properties.name), { permanent: true, direction: 'center', className: 'map-district-label' });
          layer.on('click', () => this.chooseDistrict(feature.properties.id));
          layer.on('add', () => {
            const path = layer.getElement();
            if (path) {
              path.setAttribute('tabindex', '0'); path.setAttribute('role', 'button');
              path.setAttribute('aria-label', 'Explore ' + feature.properties.name);
              path.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); this.chooseDistrict(feature.properties.id); }
              });
            }
          });
        },
      }).addTo(this.map);
      this.keralaBounds = this.geojson.getBounds();
      this.map.setMaxBounds(this.keralaBounds.pad(.6));
      this.map.fitBounds(this.keralaBounds, { padding: [25, 25], animate: false });
    }

    paintUnknown() {
      for (const layer of this.districtLayers.values()) {
        layer.setStyle({ fillColor: '#c7cec8', color: '#8c9691', fillOpacity: .65 });
        const path = layer.getElement();
        if (path) { path.dataset.alertLevel = 'UNKNOWN'; path.setAttribute('aria-label', layer.feature.properties.name + ': alert status unknown. Refresh map data.'); }
      }
      this.localityGroup.clearLayers();
      this.shelterGroup.clearLayers();
      this.map.closePopup();
    }

    paint() {
      const detailed = this.map.getZoom() >= LOCALITY_ZOOM;
      for (const district of this.data.districts) {
        const layer = this.districtLayers.get(district.id);
        if (!layer) continue;
        layer.setStyle({ fillColor: COLOURS[district.level] || '#c7cec8', fillOpacity: detailed ? .27 : .82,
          color: this.selectedDistrict === district.id ? '#245f68' : '#718e7a', weight: this.selectedDistrict === district.id ? 2.5 : 1.2 });
        const path = layer.getElement();
        if (path) { path.dataset.district = district.id; path.dataset.alertLevel = district.level;
          path.setAttribute('aria-label', district.name + ': ' + LABELS[district.level] + '. Explore district.'); }
      }
      this.localityGroup.clearLayers();
      this.localityMarkers.clear();
      for (const place of this.data.localities.filter(coordinates)) {
        const marker = L.circleMarker([place.latitude, place.longitude], {
          radius: place.own_level === 'GREEN' ? 5 : 9, color: '#fffdf5', weight: 2,
          fillColor: COLOURS[place.level] || '#aaa', fillOpacity: 1, interactive: true,
        });
        marker.bindTooltip(element('span', '', place.name + ' · ' + LABELS[place.level]), { permanent: true, direction: 'top', offset: [0, -5], className: 'map-locality-label' });
        marker.on('click', () => this.chooseLocality(place.id));
        marker.addTo(this.localityGroup);
        this.localityMarkers.set(place.id, marker);
      }
      // Keep an open shelter popup stable while its text/capacity refreshes.
      const openShelter = this.selectedShelter;
      this.shelterGroup.clearLayers();
      this.shelterMarkers.clear();
      for (const shelter of this.data.shelters.filter(coordinates)) {
        const available = shelter.status === 'OPEN' && shelter.available_capacity > 0;
        const symbol = element('span', '', '⌂'); symbol.setAttribute('aria-hidden', 'true');
        const marker = L.marker([shelter.latitude, shelter.longitude], {
          icon: L.divIcon({ html: symbol, className: 'map-shelter-icon ' + (!available ? 'unavailable' : shelter.freshness_status !== 'recent' ? 'unknown' : ''), iconSize: [29, 29], iconAnchor: [14, 29] }),
          title: shelter.name + ' · ' + (available ? shelter.available_capacity + ' recorded spaces' : shelter.status === 'CLOSED' ? 'Closed' : 'Full'),
          keyboard: true, zIndexOffset: 1000,
        });
        marker.bindPopup(this.shelterContent(shelter, true), { maxWidth: 280, autoPanPadding: [20, 35] });
        marker.on('click', () => { this.selectedShelter = shelter.id; });
        marker.on('popupclose', () => { if (this.selectedShelter === shelter.id) this.selectedShelter = null; });
        marker.addTo(this.shelterGroup);
        this.shelterMarkers.set(shelter.id, marker);
      }
      if (openShelter && this.shelterMarkers.has(openShelter)) {
        this.selectedShelter = openShelter;
        this.shelterMarkers.get(openShelter).openPopup();
      }
      this.updateZoom(false);
    }

    updateZoom(repaint = true) {
      if (!this.data || this.stale) return;
      const detailed = this.map.getZoom() >= LOCALITY_ZOOM;
      if (detailed) this.localityGroup.addTo(this.map);
      else this.localityGroup.removeFrom(this.map);
      for (const layer of this.districtLayers.values()) {
        layer.setStyle({ fillOpacity: detailed ? .27 : .82 });
        const tooltip = layer.getTooltip();
        if (tooltip) { if (detailed) layer.closeTooltip(); else layer.openTooltip(); }
      }
      for (const marker of this.localityMarkers.values()) {
        if (this.map.getZoom() >= 11) marker.openTooltip(); else marker.closeTooltip();
      }
      this.root.querySelector('.overview-map-sea').hidden = detailed;
      this.root.querySelector('[data-map-zoom-note]').textContent = detailed
        ? 'Coloured dots: locality centres · House pins: recorded shelters. Select a pin for details.'
        : 'Select a district or use + to reveal locality alerts. House pins show recorded shelters.';
    }

    selectors() {
      const districts = [...this.data.districts].sort((a, b) => a.name.localeCompare(b.name));
      this.districtSelect.replaceChildren(new Option('All Kerala', ''));
      for (const district of districts) this.districtSelect.add(new Option(district.name + ' · ' + LABELS[district.level], district.id));
      this.districtSelect.disabled = false;
      this.districtSelect.value = this.selectedDistrict;
      this.localitySelect.replaceChildren(new Option(this.selectedDistrict ? 'All localities' : 'Choose a district first', ''));
      for (const locality of this.data.localities.filter(p => p.district_id === this.selectedDistrict).sort((a, b) => a.name.localeCompare(b.name))) {
        this.localitySelect.add(new Option(locality.name + ' · ' + LABELS[locality.level], locality.id));
      }
      this.localitySelect.disabled = !this.selectedDistrict;
      this.localitySelect.value = this.selectedLocality;
    }

    chooseDistrict(id) {
      if (!this.data || this.stale) return;
      this.selectedDistrict = id;
      this.selectedLocality = '';
      this.selectedShelter = null;
      this.map.closePopup();
      const layer = this.districtLayers.get(id);
      if (layer) this.map.fitBounds(layer.getBounds(), { padding: [35, 35], maxZoom: 11, animate: !window.matchMedia('(prefers-reduced-motion: reduce)').matches });
      else if (this.keralaBounds) this.map.fitBounds(this.keralaBounds, { padding: [25, 25] });
      this.selectors(); this.paint(); this.details();
    }

    chooseLocality(id) {
      if (!this.data || this.stale) return;
      const place = this.data.localities.find(p => p.id === id);
      this.selectedLocality = place ? place.id : '';
      if (place) this.selectedDistrict = place.district_id;
      this.selectors();
      if (place && coordinates(place)) this.map.setView([place.latitude, place.longitude], 12);
      this.paint(); this.details();
    }

    alertList(alerts) {
      const list = element('ul', 'map-alert-list');
      for (const alert of [...alerts].sort((a, b) => RANK[b.level] - RANK[a.level])) {
        const item = element('li', 'map-alert-item');
        item.append(badge(alert.level), element('strong', '', alert.title), element('p', '', alert.message),
          element('p', '', 'Coverage: ' + alert.place_name + (alert.place_kind === 'district' ? ' district' : ' locality')),
          element('p', '', 'Until ' + time(alert.expires_at)));
        list.append(item);
      }
      return list;
    }

    referenceLocation() {
      if (this.origin) return this.origin;
      const place = this.data?.localities.find(p => p.id === this.selectedLocality);
      return place && coordinates(place) ? place : null;
    }

    shelterContent(shelter, popup = false) {
      const content = element(popup ? 'div' : 'li', popup ? 'map-shelter-popup' : 'map-shelter-item');
      content.append(element(popup ? 'h3' : 'strong', '', shelter.name));
      const available = shelter.status === 'OPEN' && shelter.available_capacity > 0;
      content.append(element('p', '', available ? shelter.available_capacity + ' recorded spaces · ' + shelter.occupied + '/' + shelter.capacity + ' occupied or reserved'
        : shelter.status === 'CLOSED' ? 'Closed · not accepting registrations' : 'Full · no recorded space'));
      const reference = this.referenceLocation();
      const km = distance(reference, shelter);
      if (Number.isFinite(km)) content.append(element('p', '', km.toFixed(1) + ' km straight-line from '
        + (this.origin ? 'your device location' : reference.name + ' centre') + ' · travel routes may differ'));
      content.append(element('p', '', [shelter.locality, shelter.district].filter(Boolean).join(', ') || shelter.location || 'Locality not recorded'));
      if (shelter.address) content.append(element('p', '', shelter.address));
      content.append(element('p', 'map-record-note', 'Record updated: ' + (shelter.freshness_status === 'unknown' ? 'Unknown' : time(shelter.updated_at))
        + ' · ' + (shelter.freshness_status === 'recent' ? 'Recent' : shelter.freshness_status === 'stale' ? 'Stale' : 'Unknown freshness')));
      content.append(element('p', '', 'Contact: ' + (shelter.contact || 'Not recorded. Confirm with a local response office.')));
      if (shelter.freshness_status !== 'recent') content.append(element('p', '', 'Contact the shelter before travelling; this capacity has not been confirmed recently.'));
      if (!coordinates(shelter)) content.append(element('p', '', 'Coordinates not recorded · available in this list without a map pin.'));
      let href = '/shelters?q=' + encodeURIComponent(shelter.name);
      let label = 'View shelter';
      if (this.role === 'citizen') {
        const query = new URLSearchParams();
        const district = this.data.districts.find(d => d.id === this.selectedDistrict);
        const locality = this.data.localities.find(p => p.id === this.selectedLocality);
        if (district) query.set('origin_district', district.name);
        if (locality) query.set('origin_locality', locality.name);
        href = '/shelters/' + Number(shelter.id) + '/join' + (query.size ? '?' + query : '');
        label = available ? 'Register to join' : 'View shelter / my registration';
      } else if (shelter.can_manage_registrations) {
        href = '/shelters/' + Number(shelter.id) + '/join'; label = 'Manage registrations';
      }
      content.append(link(label, href, this.role === 'citizen' && available));
      return content;
    }

    details() {
      if (!this.data || this.stale) return;
      const district = this.data.districts.find(d => d.id === this.selectedDistrict);
      const locality = this.data.localities.find(p => p.id === this.selectedLocality);
      const fragment = document.createDocumentFragment();
      fragment.append(element('h3', '', locality ? locality.name : district ? district.name : 'Across Kerala'));
      if (district || locality) {
        const selected = locality || district;
        fragment.append(badge(selected.level));
        const coverage = locality
          ? (locality.inherited_level !== 'GREEN' ? 'Includes a district-wide ' + LABELS[locality.inherited_level].toLowerCase() + '.' : 'Locality coverage is shown at the recorded place centre.')
          : district.district_level !== 'GREEN' ? 'District-wide coverage: ' + LABELS[district.district_level] + '. Local alerts may be higher.'
            : district.active_alert_count ? 'The district colour summarises locality alerts. There is no district-wide alert.' : 'No active administrator-issued alert for this district.';
        fragment.append(element('p', '', coverage));
        if (locality && !coordinates(locality)) fragment.append(element('p', 'map-unavailable-note', 'This locality has no verified map point. Its alerts are still listed here.'));
        if (selected.alerts.length) fragment.append(this.alertList(selected.alerts));
        else fragment.append(element('p', '', 'No active admin alert is recorded here. Check official updates before travel.'));
        if (district && !locality) {
          const localities = this.data.localities.filter(p => p.district_id === district.id && p.own_level !== 'GREEN');
          if (localities.length) {
            fragment.append(element('h4', '', 'Locality alerts'));
            const list = element('div', 'map-locality-list');
            for (const place of localities.sort((a, b) => RANK[b.level] - RANK[a.level])) {
              const button = element('button', 'map-locality-button', place.name + (!coordinates(place) ? ' · no map point' : ''));
              button.type = 'button'; button.append(badge(place.level)); button.addEventListener('click', () => this.chooseLocality(place.id)); list.append(button);
            }
            fragment.append(list);
          }
        }
      } else {
        fragment.append(element('p', '', this.data.districts.reduce((n, d) => n + d.active_alert_count, 0) + ' active admin alerts · 14 districts. Select a district or zoom to explore.'));
        const list = element('ul', 'map-district-list');
        for (const item of [...this.data.districts].sort((a, b) => RANK[b.level] - RANK[a.level] || a.name.localeCompare(b.name))) {
          const row = element('li'); const button = element('button', '', item.name); button.type = 'button';
          button.append(badge(item.level)); button.addEventListener('click', () => this.chooseDistrict(item.id)); row.append(button); list.append(row);
        }
        fragment.append(list);
      }
      let shelters = [...this.data.shelters];
      if (district) shelters = shelters.filter(s => s.district_id === district.id || (!s.district_id && (s.district || '').toLocaleLowerCase() === district.name.toLocaleLowerCase()));
      const reference = this.referenceLocation();
      shelters.sort((a, b) => (a.status === 'OPEN' && a.available_capacity > 0 ? 0 : 1) - (b.status === 'OPEN' && b.available_capacity > 0 ? 0 : 1)
        || (reference ? distance(reference, a) - distance(reference, b) : 0) || a.name.localeCompare(b.name));
      fragment.append(element('h4', '', (reference ? 'Nearby recorded shelters' : 'Recorded shelters') + ' · ' + shelters.length));
      if (shelters.length) {
        const list = element('ul', 'map-shelter-list');
        for (const shelter of shelters) list.append(this.shelterContent(shelter));
        fragment.append(list);
      } else fragment.append(element('p', '', 'No shelter records match this area. This does not establish that no shelter exists.'));
      if (this.data.unlocated_shelter_count || this.data.unlocated_alert_count) fragment.append(element('p', '', this.data.unlocated_shelter_count + ' shelter record(s) and ' + this.data.unlocated_alert_count + ' locality alert(s) have no verified coordinates. They remain available in the lists.'));
      fragment.append(link('Browse all shelters', '/shelters'));
      this.panel.replaceChildren(fragment);
      process(this.panel);
    }

    attribution(data) {
      const target = this.root.querySelector('[data-map-attribution]');
      target.replaceChildren(document.createTextNode((data?.boundary || 'District boundaries: geoBoundaries.') + ' ' + (data?.points || '')));
      for (const source of data?.source_urls || []) {
        if (!/^https:\/\/(www\.)?(geoboundaries\.org|geonames\.org|openstreetmap\.org)\//.test(source)) continue;
        const anchor = element('a', '', source.includes('geonames') ? 'GeoNames attribution' : source.includes('openstreetmap') ? 'OpenStreetMap attribution' : 'Boundary source');
        anchor.href = source; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer';
        target.append(document.createTextNode(' · '), anchor);
      }
    }

    locate() {
      const note = this.root.querySelector('[data-map-location-note]');
      if (!navigator.geolocation) { note.textContent = 'Location is unavailable in this browser. Choose a district and locality instead.'; return; }
      note.textContent = 'Waiting for your permission to read this device’s location…';
      navigator.geolocation.getCurrentPosition(position => {
        if (this.destroyed) return;
        this.origin = { latitude: position.coords.latitude, longitude: position.coords.longitude };
        if (this.userMarker) this.userMarker.remove();
        this.userMarker = L.marker([this.origin.latitude, this.origin.longitude], { icon: L.divIcon({ className: 'map-user-marker', iconSize: [15, 15] }), title: 'Your approximate device location' }).addTo(this.map);
        const accuracy = Math.max(1, Math.round(position.coords.accuracy));
        note.textContent = 'Shelters sorted using your device location (accuracy about ' + accuracy.toLocaleString() + ' m). Distances are straight-line estimates, not safe routes. Location stays in this page.';
        this.details();
      }, () => { if (!this.destroyed) note.textContent = 'Location could not be read. Choose a district and locality instead; you can still register for a shelter.'; },
      { enableHighAccuracy: false, timeout: 12000, maximumAge: 60000 });
    }

    destroy() {
      this.destroyed = true; this.controller.abort(); window.clearInterval(this.timer);
      document.removeEventListener('visibilitychange', this.onVisibility);
      this.resizeObserver.disconnect(); this.map.remove(); this.origin = null;
    }
  }

  function initialize() {
    const root = document.querySelector('[data-overview-map]');
    if (active && active.root !== root) { active.destroy(); active = null; }
    if (!root || active) return;
    if (!window.L) { root.querySelector('[data-map-status]').textContent = 'The map could not load. Use the alert and shelter lists to browse records.'; return; }
    try { active = new OverviewMap(root); } catch { root.querySelector('[data-map-status]').textContent = 'The map could not start. Use the alert and shelter lists to browse records.'; }
  }
  document.addEventListener('DOMContentLoaded', initialize);
  document.addEventListener('htmx:afterSettle', initialize);
  document.addEventListener('htmx:beforeCleanupElement', event => {
    if (active && (event.detail.elt === active.root || event.detail.elt.contains(active.root))) { active.destroy(); active = null; }
  });
  window.addEventListener('pagehide', () => { if (active) { active.destroy(); active = null; } });
})();
