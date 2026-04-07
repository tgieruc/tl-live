<script lang="ts">
	import { onMount } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { LINE_COLORS } from '$lib/types';

	// Censuy coordinates
	const CENTER: [number, number] = [6.583961, 46.532379];

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map;

	async function loadRoutes(m: maplibregl.Map) {
		const [routesRes, stopsRes] = await Promise.all([
			fetch('/api/routes'),
			fetch('/api/stops')
		]);
		const routes = await routesRes.json();
		const stops = await stopsRes.json();

		m.addSource('routes', { type: 'geojson', data: routes });

		for (const [line, color] of Object.entries(LINE_COLORS)) {
			m.addLayer({
				id: `route-glow-${line}`,
				type: 'line',
				source: 'routes',
				filter: ['==', ['get', 'line'], line],
				layout: { 'line-join': 'round', 'line-cap': 'round' },
				paint: { 'line-color': color, 'line-width': 8, 'line-opacity': 0.15, 'line-blur': 4 }
			});
			m.addLayer({
				id: `route-line-${line}`,
				type: 'line',
				source: 'routes',
				filter: ['==', ['get', 'line'], line],
				layout: { 'line-join': 'round', 'line-cap': 'round' },
				paint: { 'line-color': color, 'line-width': 3, 'line-opacity': 0.7 }
			});
		}

		m.addSource('stops', { type: 'geojson', data: stops });
		m.addLayer({
			id: 'stops-dot',
			type: 'circle',
			source: 'stops',
			paint: { 'circle-color': '#ffffff', 'circle-radius': 3, 'circle-stroke-width': 1, 'circle-stroke-color': '#0a0a0a', 'circle-opacity': 0.6 }
		});
		m.addLayer({
			id: 'stops-label',
			type: 'symbol',
			source: 'stops',
			minzoom: 15,
			layout: { 'text-field': ['get', 'name'], 'text-size': 10, 'text-offset': [0, 1.2], 'text-anchor': 'top', 'text-font': ['Noto Sans Regular'], 'text-max-width': 8 },
			paint: { 'text-color': '#888888', 'text-halo-color': '#0a0a0a', 'text-halo-width': 1.5 }
		});
	}

	async function updateBusPositions(m: maplibregl.Map) {
		try {
			const res = await fetch('/api/positions');
			const data = await res.json();
			const source = m.getSource('buses') as maplibregl.GeoJSONSource;
			if (source) {
				source.setData(data);
			}
		} catch (e) {
			console.error('Failed to fetch positions', e);
		}
	}

	onMount(() => {
		map = new maplibregl.Map({
			container: mapContainer,
			style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
			center: CENTER,
			zoom: 14.5,
			attributionControl: false
		});

		map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
		map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');

		map.on('load', async () => {
			await loadRoutes(map);

			// Censuy home marker
			map.addSource('home-stop', {
				type: 'geojson',
				data: {
					type: 'FeatureCollection',
					features: [{
						type: 'Feature',
						geometry: { type: 'Point', coordinates: CENTER },
						properties: { name: 'Censuy' }
					}]
				}
			});
			map.addLayer({
				id: 'home-stop-glow', type: 'circle', source: 'home-stop',
				paint: { 'circle-color': '#00d4aa', 'circle-radius': 18, 'circle-opacity': 0.15, 'circle-blur': 1 }
			});
			map.addLayer({
				id: 'home-stop-dot', type: 'circle', source: 'home-stop',
				paint: { 'circle-color': '#00d4aa', 'circle-radius': 6, 'circle-stroke-width': 2, 'circle-stroke-color': '#0a0a0a' }
			});
			map.addLayer({
				id: 'home-stop-label', type: 'symbol', source: 'home-stop',
				layout: { 'text-field': 'Censuy', 'text-size': 12, 'text-offset': [0, 1.5], 'text-anchor': 'top', 'text-font': ['Noto Sans Regular'] },
				paint: { 'text-color': '#00d4aa', 'text-halo-color': '#0a0a0a', 'text-halo-width': 2 }
			});

			// Bus positions source (updated by polling)
			map.addSource('buses', {
				type: 'geojson',
				data: { type: 'FeatureCollection', features: [] }
			});

			for (const [line, color] of Object.entries(LINE_COLORS)) {
				map.addLayer({
					id: `bus-glow-${line}`, type: 'circle', source: 'buses',
					filter: ['==', ['get', 'line'], line],
					paint: { 'circle-color': color, 'circle-radius': 14, 'circle-opacity': 0.25, 'circle-blur': 1 }
				});
				map.addLayer({
					id: `bus-dot-${line}`, type: 'circle', source: 'buses',
					filter: ['==', ['get', 'line'], line],
					paint: { 'circle-color': color, 'circle-radius': 7, 'circle-stroke-width': 2, 'circle-stroke-color': '#0a0a0a' }
				});
				map.addLayer({
					id: `bus-label-${line}`, type: 'symbol', source: 'buses',
					filter: ['==', ['get', 'line'], line],
					layout: { 'text-field': ['get', 'line'], 'text-size': 9, 'text-font': ['Noto Sans Regular'] },
					paint: { 'text-color': '#ffffff' }
				});
			}

			// Initial position fetch
			await updateBusPositions(map);
		});

		const positionInterval = setInterval(() => {
			if (map) updateBusPositions(map);
		}, 5000);

		return () => {
			clearInterval(positionInterval);
			map.remove();
		};
	});

	export function getMap(): maplibregl.Map {
		return map;
	}
</script>

<div bind:this={mapContainer} class="absolute inset-0 w-full h-full"></div>

<style>
	:global(.maplibregl-ctrl-group) {
		border-radius: 0 !important;
		box-shadow: 0 0 8px rgba(0, 212, 170, 0.15) !important;
		border: 1px solid #333 !important;
		background: #0a0a0a !important;
	}
	:global(.maplibregl-ctrl-group button) {
		width: 32px !important;
		height: 32px !important;
		background-color: #0a0a0a !important;
		border-bottom-color: #333 !important;
	}
	:global(.maplibregl-ctrl-group button:hover) {
		background-color: #1a1a1a !important;
	}
	:global(.maplibregl-ctrl-group button .maplibregl-ctrl-icon) {
		filter: invert(1) !important;
	}
	:global(.maplibregl-ctrl-attrib) {
		font-size: 10px !important;
		font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace !important;
		background: rgba(0, 0, 0, 0.8) !important;
		color: #666 !important;
	}
	:global(.maplibregl-ctrl-attrib a) {
		color: #666 !important;
	}
</style>
