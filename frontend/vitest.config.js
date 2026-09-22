import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Separate from vite.config.js deliberately: the app config wires the Tailwind
// vite plugin and a dev-only /api proxy, neither of which the test runner
// needs (and the Tailwind plugin's PostCSS pipeline is not exercised in jsdom).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
    restoreMocks: true,
    // format.test.js and Sources.test.jsx each pin `process.env.TZ` for the
    // duration of their run (to make timezone-dependent date-parsing bugs
    // reproducible regardless of the host's real timezone). process.env is
    // shared by the whole worker process, so running files concurrently
    // races: one file's afterAll can restore TZ mid-way through another
    // file's assertions. Keep file execution sequential to avoid that.
    fileParallelism: false,
    server: {
      deps: {
        // @material/material-color-utilities@0.4.0 ships ESM ("type": "module")
        // with extensionless relative imports (e.g. `from './dynamic_color'`
        // instead of './dynamic_color.js'), which Vite/esbuild tolerate but
        // strict Node ESM resolution does not. Vite bundles it fine for `vite
        // build`; force Vitest to run it through the same Vite transform
        // pipeline instead of loading it as a native Node module, or every
        // test importing theme.js fails with ERR_MODULE_NOT_FOUND.
        inline: ['@material/material-color-utilities'],
      },
    },
  },
})
