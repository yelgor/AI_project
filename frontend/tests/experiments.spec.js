import {test,expect} from '@playwright/test';

test('real experiment replay, causal timeline, map layers and ZIP',async({page,request})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const runs=await (await request.get('/api/experiments')).json();
  const run=runs.find(r=>r.status==='RECOVERED_WAIT');
  expect(run,'Run scripts/check_navigation_experiments.py before the browser check').toBeTruthy();
  await page.goto('/experiments.html');
  await page.locator(`[data-run="${run.experiment_id}"]`).click();
  await expect(page.locator('#time')).toContainText('REPLAY');
  await expect(page.locator('#map')).toBeVisible();
  await expect.poll(()=>page.evaluate(()=>window.experimentLab?.atTime()?.observations.length||0)).toBeGreaterThan(1);
  const finalCount=await page.evaluate(()=>window.experimentLab.atTime().observations.length);
  await page.locator('#timeline').evaluate(node=>{node.value=String((Number(node.min)+Number(node.max))/2);node.dispatchEvent(new Event('input',{bubbles:true}));});
  const earlier=await page.evaluate(()=>window.experimentLab.atTime());
  expect(earlier.observations.length).toBeLessThan(finalCount);
  expect(earlier.map?.observation_count||0).toBeLessThanOrEqual(earlier.observations.length);
  await page.locator('#layer').selectOption('mean');
  await page.locator('#layer').selectOption('std');
  await expect(page.locator('#legend')).toContainText('GPR');
  const download=page.waitForEvent('download');
  await page.locator(`a[href="/api/experiments/${run.experiment_id}.zip"]`).click();
  expect((await download).suggestedFilename()).toContain(run.experiment_id);
  await page.screenshot({path:'test-results/experiments.png',fullPage:true});
  expect(errors).toEqual([]);
});
