<script lang="ts">
	import '../app.css';
	let { children } = $props();
</script>

<svelte:head>
	<title>TL Dashboard</title>
</svelte:head>

{@render children()}
