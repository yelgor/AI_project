import {test,expect} from '@playwright/test';

test('research dashboard exposes actual learning, heldout scores and all failures without mutating the runtime',async({page,request})=>{
 const errors=[],posts=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
 const before=await(await request.get('/api/experiments')).json();
 await page.goto('/research.html');
 await expect.poll(()=>page.evaluate(()=>window.researchLab?.field())).toBe('district-a');
 await expect(page.locator('#hardware-status')).toContainText('на фізичному Husky не перевірено');
 await expect(page.locator('#cohort-cards')).toContainText('39/40');
 await expect(page.locator('#cohort-cards')).toContainText('18/20');
 await expect(page.locator('#cohort-cards')).toContainText('20/20');
 await expect(page.locator('#test-scores')).toContainText('7.25 dB');
 const late=await page.evaluate(()=>window.researchLab.frame());
 await page.locator('#prefix').fill('0');
 await expect(page.locator('#prefix-count')).toHaveText('4');
 const early=await page.evaluate(()=>window.researchLab.frame());
 expect(early.training_count).toBeLessThan(late.training_count);
 expect(early.score.test_count).toBe(late.score.test_count);
 expect(early.mean_dbm).not.toEqual(late.mean_dbm);
 await page.locator('#profile').selectOption('gpr-tuned');
 expect((await page.evaluate(()=>window.researchLab.frame())).profile).toBe('gpr-tuned');
 await page.locator('#map-layer').selectOption('std');
 await page.locator('#profile').selectOption('idw');
 expect((await page.evaluate(()=>window.researchLab.frame())).std_db.every(v=>v===null)).toBeTruthy();
 await page.locator('#field').selectOption('warehouse-b');
 await expect(page.locator('#prediction')).toBeVisible();
 expect(await page.locator('#field').textContent()).not.toContain('courtyard');
 await page.locator('#outcome-filter').selectOption('failed');
 await expect(page.locator('#trial-count')).toHaveText('3 GPR-проїздів · 0 успішних · 3 невдалих');
 expect(await page.locator('#trial-table tbody tr').count()).toBe(3);
 const download=page.waitForEvent('download');
 await page.locator('a[href="/api/research/files/map-scores.csv"]').click();
 expect((await download).suggestedFilename()).toBe('map-scores.csv');
 await page.locator('#profile').selectOption('gpr-baseline');await page.locator('#field').selectOption('district-a');await page.locator('#map-layer').selectOption('mean');
 await page.screenshot({path:'test-results/model-evidence.png',fullPage:true});
 await page.locator('#full-gpr-demo a.button').click();
 await expect.poll(()=>page.evaluate(()=>window.experimentLab?.getReplay()?.manifest.config.method)).toBe('GPR-pathloss');
 expect(await page.evaluate(()=>window.experimentLab.getReplay().manifest.config.history_from)).toBe('');
 await expect.poll(()=>page.evaluate(()=>window.experimentLab?.getSurfaceStats()?.triangles||0)).toBeGreaterThan(0);
 await expect(page.locator('#source-badge')).toContainText('ЗАПИС');
 await page.locator('#replay-reset').click();
 expect(await page.locator('#timeline').inputValue()).toBe(await page.locator('#timeline').getAttribute('min'));
 const after=await(await request.get('/api/experiments')).json();
 expect(after.map(r=>r.experiment_id).sort()).toEqual(before.map(r=>r.experiment_id).sort());
 expect(posts).toEqual([]);expect(errors).toEqual([]);
});

test('curated GPR replay opens directly from archives and remains causal and read only',async({page,request})=>{
 const posts=[],errors=[];page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});page.on('pageerror',e=>errors.push(e.message));
 const overview=await(await request.get('/api/research')).json(),e=overview.examples.gpr_failure;
 // A fresh checkout needs no import; the replay is read directly from the bundled nested ZIP.
 await page.goto(`/experiments.html?evidence=${e.cohort}&run=${e.experiment_id}&layer=mean&phase=decision`);
 await expect.poll(()=>page.evaluate(()=>window.experimentLab?.getReplay()?.manifest.experiment_id)).toBe(e.experiment_id);
 await expect(page.locator('#selected-record')).toContainText('GPR-pathloss');
 await expect(page.locator('#selected-record')).toContainText('без імпорту');
 await expect(page.locator('#source-badge')).toContainText('ЗАПИС');
 await expect(page.locator('#layer')).toHaveValue('mean');
 await expect.poll(()=>page.evaluate(()=>window.experimentLab.getMeshCount())).toBe(6);
 const decision=await page.evaluate(()=>window.experimentLab.atTime());
 expect(decision.map).toBeTruthy();expect(decision.map.observation_count).toBeLessThanOrEqual(decision.observations.length);
 await page.locator('#timeline').evaluate(n=>{n.value=n.max;n.dispatchEvent(new Event('input',{bubbles:true}));});
 await expect(page.locator('#mode')).toContainText('помилкою');
 await page.keyboard.press('Space');await page.keyboard.press('ArrowUp');
 await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
 expect(posts).toEqual([]);
 const download=page.waitForEvent('download');await page.locator('#selected-record a[download]').click();
 expect((await download).suggestedFilename()).toContain(e.experiment_id);
 expect(errors).toEqual([]);
});

test('new GPR mission link selects the model but never launches it automatically',async({page})=>{
 const starts=[];page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/api/mission/start'))starts.push(r.url());});
 await page.goto('/experiments.html?method=GPR-pathloss&beta=1');
 await expect(page.locator('#method')).toHaveValue('GPR-pathloss');
 await expect(page.locator('#beta')).toHaveValue('1');
 await expect(page.locator('#beta')).toBeEnabled();expect(starts).toEqual([]);
});

test('3D RSSI surface follows recorded predictions, scales and explicitly selected reference',async({page,request})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const overview=await(await request.get('/api/research')).json(),e=overview.examples.gpr_success;
 await page.goto(`/experiments.html?evidence=${e.cohort}&run=${e.experiment_id}&layer=height&phase=decision`);
 await expect.poll(()=>page.evaluate(()=>window.experimentLab?.getSurfaceStats()?.triangles||0)).toBeGreaterThan(10);
 await expect(page.locator('#signal-height-legend')).toBeVisible();
 await expect(page.locator('#map-scale')).toContainText('ПРОГНОЗ');
 const original=await page.evaluate(()=>({surface:window.experimentLab.getSurfaceStats(),data:window.experimentLab.atTime()}));
 expect(original.surface.observation_count).toBeLessThanOrEqual(original.data.observations.length);
 expect(original.surface.maximum_height).toBeGreaterThan(original.surface.minimum_height);
 await page.locator('#surface-scale').selectOption('16');
 expect((await page.evaluate(()=>window.experimentLab.getSurfaceStats())).maximum_height).toBeGreaterThan(original.surface.maximum_height);
 await page.locator('#reference-select').selectOption('evidence');
 await expect(page.locator('#layer')).toHaveValue('reference-height');
 await expect(page.locator('#source-badge')).toContainText('ЕТАЛОН ПІСЛЯ ЕКСПЕРИМЕНТУ');
 expect((await page.evaluate(()=>window.experimentLab.getSurfaceStats())).source).toBe('reference');
 expect((await page.evaluate(()=>window.experimentLab.atTime().observations.length))).toBe(original.data.observations.length);
 await page.screenshot({path:'test-results/radio-height-reference.png',fullPage:true});
 await page.locator('#layer').selectOption('height');
 await page.screenshot({path:'test-results/radio-height-prediction.png',fullPage:true});
 await page.locator('#surface-toggle').click();await expect(page.locator('#layer')).toHaveValue('mean');
 expect(await page.evaluate(()=>window.experimentLab.getSurfaceStats())).toBeNull();
 await page.locator('[data-tab="live"]').click();
 await expect(page.locator('#layer option[value="reference-height"]')).toBeDisabled();
 expect(errors).toEqual([]);
});

test('live Gazebo GPR mission updates its 3D signal surface as Husky moves and recovers',async({page})=>{
 test.setTimeout(420000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/experiments.html?method=GPR-pathloss&beta=1');
 await expect(page.locator('#layer')).toHaveValue('height');await page.locator('#start-mission').click();
 await expect.poll(()=>page.evaluate(()=>window.experimentLab?.getSurfaceStats()?.observation_count||0),{timeout:180000}).toBeGreaterThan(3);
 const first=await page.evaluate(()=>window.experimentLab.getSurfaceStats());
 await expect.poll(()=>page.evaluate(()=>window.experimentLab.getSurfaceStats()?.observation_count||0),{timeout:60000}).toBeGreaterThan(first.observation_count+4);
 await expect(page.locator('#map-scale')).toContainText('ПРОГНОЗ');
 await expect(page.locator('#source-badge')).toContainText('LIVE · Gazebo');
 await expect(page.locator('#layer option[value="reference-height"]')).toBeDisabled();
 await page.screenshot({path:'test-results/radio-height-live.png',fullPage:true});
 await expect.poll(()=>page.evaluate(()=>window.experimentLab.getState()?.experiment?.status),{timeout:240000}).toBe('RECOVERED_WAIT');
 const state=await page.evaluate(()=>window.experimentLab.getState());
 expect(state.experiment.config.loss_policy).toBe('responsive');
 expect(state.experiment.metrics.brake_distance_m).toBeLessThan(.5);
 const run=await(await page.request.get('/api/experiments/'+state.experiment.experiment_id)).json();
 const suspect=run.timeline.find(e=>e.kind==='mode'&&e.mode==='LINK_SUSPECT'),brake=run.timeline.find(e=>e.kind==='brake'),target=run.timeline.find(e=>e.kind==='target');
 expect(suspect).toBeTruthy();expect(brake.sequence).toBeLessThan(target.sequence);
 expect(Math.hypot(...brake.pose.linear_velocity)).toBeLessThan(.03);
 expect(Math.hypot(...suspect.pose.position.slice(0,2).map((x,i)=>x-state.experiment.config.shadow_goal[i]))).toBeGreaterThan(state.experiment.config.shadow_radius_m);
 await page.screenshot({path:'test-results/responsive-recovered.png',fullPage:true});
 expect(errors).toEqual([]);
});


test('focused height scale and fullscreen make small RSSI changes visible without changing data',async({page,request})=>{
 const o=await(await request.get('/api/research')).json(),e=o.examples.gpr_success;
 await page.goto(`/experiments.html?evidence=${e.cohort}&run=${e.experiment_id}&phase=decision`);
 await expect.poll(()=>page.evaluate(()=>window.experimentLab?.getSurfaceStats()?.triangles||0)).toBeGreaterThan(0);
 await expect(page.locator('#layer')).toHaveValue('height');
 expect((await page.evaluate(()=>window.experimentLab.getSurfaceStats())).range_dbm).toEqual([-67,-27]);
 const values=await page.evaluate(()=>window.experimentLab.atTime().map.cells.map(c=>c.mean_dbm));
 await page.locator('#surface-sensitivity').selectOption('20');
 expect((await page.evaluate(()=>window.experimentLab.getSurfaceStats())).range_dbm).toEqual([-57,-37]);
 expect(await page.evaluate(()=>window.experimentLab.atTime().map.cells.map(c=>c.mean_dbm))).toEqual(values);
 await expect(page.locator('#map-stop')).toBeDisabled();
 await page.locator('#map-fullscreen').click();
 await expect.poll(()=>page.evaluate(()=>Boolean(document.fullscreenElement))).toBe(true);
 await expect(page.locator('#map-fullscreen')).toHaveText('Згорнути');
 await page.screenshot({path:'test-results/radio-sensitive-fullscreen.png',fullPage:true});
 await page.locator('#map-fullscreen').click();
 await expect.poll(()=>page.evaluate(()=>Boolean(document.fullscreenElement))).toBe(false);
});

test('responsive demo opens from the report with its own braking protocol and no mismatched reference',async({page})=>{
 await page.goto('/research.html');
 await expect(page.locator('#responsive-gpr-demo')).toContainText('0.29 m');
 await page.locator('#responsive-gpr-demo a.button').click();
 await expect.poll(()=>page.evaluate(()=>window.experimentLab?.getReplay()?.manifest.config.loss_policy)).toBe('responsive');
 await expect(page.locator('#layer')).toHaveValue('height');
 await expect(page.locator('#reference-select')).toContainText('еталон ще не зібрано');
 expect(await page.locator('#reference-select option').count()).toBe(1);
 await expect(page.locator('#link-status')).toContainText('швидка реакція');
 const run=await page.evaluate(()=>window.experimentLab.getReplay());
 const brake=run.timeline.find(e=>e.kind==='brake');
 await page.locator('#timeline').fill(String(brake.sim_time_s));
 const data=await page.evaluate(()=>window.experimentLab.atTime());
 expect(['LINK_DEGRADED','RECOVERY']).toContain(data.mode);
});
