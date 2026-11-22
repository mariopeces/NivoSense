// Evidence only (not in the repo): serve the T4.3 build with a local catalogue, proxying the real true colour
// PMTiles of the staging scratch catalogue by range instead of copying 2 GB.
export default {
  root: "C:/Users/mario/orca/workspaces/NivoSense/plan-timeline/frontend",
  base: "./",
  build: { outDir: "C:/Users/mario/orca/workspaces/NivoSense/plan-timeline/.playwright-mcp/dist-t43" },
  preview: {
    port: 4173,
    strictPort: true,
    proxy: {
      "/localcat/staging/tiles/rgb": {
        target: "https://storage.googleapis.com",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/localcat\/staging/, "/nivosense-cogs/staging/_scratch/t04-evidence-98f90df/staging"),
      },
    },
  },
};
