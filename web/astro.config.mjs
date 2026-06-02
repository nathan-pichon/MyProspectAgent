// @ts-check
import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

// On GitHub Pages project sites the app is served from /<repo>/, so assets need
// a base path. The deploy workflow sets PAGES_BASE=/myprospectagent; locally it's
// unset (base '/') so `npm run dev` and Vercel work unchanged.
const base = process.env.PAGES_BASE || '/';

// https://astro.build/config
export default defineConfig({
  output: 'static',
  base,
  vite: {
    plugins: [tailwindcss()],
  },
});
