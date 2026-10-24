import {defineConfig} from 'vite';
import {fileURLToPath} from 'node:url';
export default defineConfig({server:{proxy:{'/api':'http://127.0.0.1:8010','/assets/husky':'http://127.0.0.1:8010','/health':'http://127.0.0.1:8010'}},build:{target:'es2022',rollupOptions:{input:{
  constructor:fileURLToPath(new URL('./index.html',import.meta.url)),
  experiments:fileURLToPath(new URL('./experiments.html',import.meta.url))
}}}});
