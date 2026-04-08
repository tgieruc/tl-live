<script lang="ts">
	import { onMount } from 'svelte';
	import type { Departure, DeparturesResponse } from '$lib/types';
	import { getLineColor } from '$lib/types';

	let departures = $state<Departure[]>([]);
	let loading = $state(true);
	let now = $state(new Date());

	function minutesUntil(departureTime: string, delay: number | null): number {
		const dep = new Date(departureTime);
		const delayMs = (delay ?? 0) * 60_000;
		const diff = dep.getTime() + delayMs - now.getTime();
		return Math.max(0, Math.round(diff / 60_000));
	}

	async function fetchDepartures() {
		try {
			const res = await fetch('/api/departures');
			const data: DeparturesResponse = await res.json();
			departures = data.departures
				.sort((a, b) => {
					const aTime = new Date(a.departure).getTime() + (a.delay ?? 0) * 60_000;
					const bTime = new Date(b.departure).getTime() + (b.delay ?? 0) * 60_000;
					return aTime - bTime;
				})
				.slice(0, 12);
		} catch (e) {
			console.error('Failed to fetch departures', e);
		}
		loading = false;
	}

	onMount(() => {
		fetchDepartures();
		const departurePoll = setInterval(fetchDepartures, 30_000);
		const clockTick = setInterval(() => (now = new Date()), 1_000);
		return () => {
			clearInterval(departurePoll);
			clearInterval(clockTick);
		};
	});
</script>

<div class="flex flex-col h-full bg-bg-card/90 backdrop-blur-sm border-l border-border">
	<div class="flex items-center justify-between px-4 py-3 border-b border-border">
		<h2 class="text-sm font-bold text-accent tracking-wider uppercase">Departures</h2>
		<span class="text-xs text-text-dim font-mono">
			{now.toLocaleTimeString('fr-CH', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
		</span>
	</div>

	<div class="flex-1 overflow-y-auto">
		{#if loading}
			<div class="flex items-center justify-center h-full text-text-dim text-sm">Loading...</div>
		{:else}
			{#each departures as dep}
				{@const mins = minutesUntil(dep.departure, dep.delay)}
				<div
					class="flex items-center gap-3 px-4 py-2.5 border-b border-border/50 hover:bg-white/[0.02] transition-colors"
				>
					<span
						class="w-10 h-7 flex items-center justify-center rounded text-xs font-bold text-black shrink-0"
						style="background-color: {getLineColor(dep.line)}"
					>
						{dep.line}
					</span>

					<div class="flex-1 min-w-0">
						<div class="text-sm truncate">{dep.destination}</div>
						<div class="text-xs text-text-dim truncate">{dep.stop_name}</div>
					</div>

					<div class="text-right shrink-0">
						{#if mins <= 0}
							<span class="text-accent text-sm font-bold">now</span>
						{:else}
							<span class="text-sm font-bold">{mins}</span>
							<span class="text-xs text-text-dim">min</span>
						{/if}
						{#if dep.delay && dep.delay > 0}
							<div class="text-xs text-delay">+{dep.delay}'</div>
						{/if}
					</div>
				</div>
			{/each}
		{/if}
	</div>
</div>
