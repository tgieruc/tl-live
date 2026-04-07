<script lang="ts">
	import Map from '$lib/components/Map.svelte';
	import DepartureBoard from '$lib/components/DepartureBoard.svelte';
</script>

<div class="h-screen w-screen flex">
	<div class="flex-1 relative">
		<Map />
	</div>
	<div class="w-80 shrink-0">
		<DepartureBoard />
	</div>
</div>
