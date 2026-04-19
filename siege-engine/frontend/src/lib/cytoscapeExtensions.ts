// Registers the cytoscape-elk layout extension on module load.
//
// Cytoscape extensions register side-effectfully via `cytoscape.use(...)`.
// This module is imported from `main.tsx` so the registration happens
// once per app boot, before any cytoscape instance is created by the
// graph components. Importing it elsewhere (e.g. from the component
// that uses the layout) is safe but depends on load order — centralizing
// here avoids accidentally rendering cytoscape before the extension
// lands.
import cytoscape from 'cytoscape';
// @ts-expect-error cytoscape-elk ships without types and the shim
// in src/types isn't picked up under the current bundler/build config.
import elk from 'cytoscape-elk';

cytoscape.use(elk);
