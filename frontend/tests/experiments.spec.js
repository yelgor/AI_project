import {test,expect} from '@playwright/test';

test('official Husky, mounted receiver, causal 3D replay and separate live mode',async({page,request})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const runs=await (await request.get('/api/experiments')).json();
  const run=runs.find(r=>r.status==='RECOVERED_WAIT'&&r.metrics?.recovery_path_length_m>1&&r.metrics?.loss_line_of_sight===false);
  expect(run,'Collect a physical shadow mission first').toBeTruthy();
  await page.goto('/experiments.html');
  await expect.poll(()=>page.evaluate(()=>window.experimentLab?.getMeshCount()||0)).toBe(6);
  await page.locator('[data-tab="replay"]').click();
  await page.locator(`[data-record="${run.experiment_id}"]`).click();
  await expect(page.locator('#source-badge')).toContainText('ЗАПИС');
  await expect(page.locator('#viewport canvas')).toBeVisible();
  await expect.poll(()=>page.evaluate(()=>window.experimentLab?.atTime()?.observations.length||0)).toBeGreaterThan(1);
  const finalCount=await page.evaluate(()=>window.experimentLab.atTime().observations.length);
  const positions=await page.evaluate(()=>({robot:window.experimentLab.robotPosition(),rx:window.experimentLab.receiverPosition()}));
  expect(Math.hypot(...positions.rx.map((x,i)=>x-positions.robot[i]))).toBeCloseTo(.7,4);
  await page.locator('#timeline').evaluate(node=>{node.value=String((Number(node.min)+Number(node.max))/2);node.dispatchEvent(new Event('input',{bubbles:true}));});
  const earlier=await page.evaluate(()=>window.experimentLab.atTime());
  expect(earlier.observations.length).toBeLessThan(finalCount);
  expect(earlier.map?.observation_count||0).toBeLessThanOrEqual(earlier.observations.length);
  await page.locator('#layer').selectOption('mean');
  await page.locator('#layer').selectOption('std');
  const reference=page.locator('#reference-select option').nth(1);
  if(await reference.count()){
    const available=await page.evaluate(()=>window.experimentLab.atTime().observations.length);
    await page.locator('#reference-select').selectOption(await reference.getAttribute('value'));
    await expect(page.locator('#source-badge')).toContainText('ЕТАЛОН ПІСЛЯ ЕКСПЕРИМЕНТУ');
    expect(await page.evaluate(()=>window.experimentLab.atTime().observations.length)).toBe(available);
  }
  const download=page.waitForEvent('download');
  await page.locator('#selected-record a[download]').click();
  expect((await download).suggestedFilename()).toContain(run.experiment_id);
  await page.screenshot({path:'test-results/mission-replay.png',fullPage:true});
  await page.locator('[data-tab="live"]').click();
  await expect(page.locator('#source-badge')).not.toContainText('ЗАПИС');
  await expect(page.locator('#replay-controls')).toBeHidden();
  expect(errors).toEqual([]);
});

test('one button prepares a physical Gazebo shadow mission and recovers',async({page})=>{
 test.setTimeout(420000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/experiments.html');
 await page.locator('#mission-select').selectOption('shadow');
 await page.locator('#start-mission').click();
 await expect(page.locator('#start-mission')).toBeDisabled();
 await expect.poll(()=>page.evaluate(()=>window.experimentLab?.getState()?.experiment?.status),{timeout:360000}).toBe('RECOVERED_WAIT');
 const state=await page.evaluate(()=>window.experimentLab.getState());
 expect(state.experiment.metrics.loss_line_of_sight).toBe(false);
 expect(state.experiment.metrics.recovery_path_length_m).toBeGreaterThan(1);
 expect(Object.keys(state.robot_pose.joint_positions).length).toBeGreaterThanOrEqual(4);
 await expect(page.locator('#source-badge')).toContainText('LIVE · Gazebo');
 await expect(page.locator('#mode')).toContainText('Зв’язок відновлено');
 await page.locator('#robot-close').click();
 await page.screenshot({path:'test-results/mission-recovered.png',fullPage:true});
 expect(errors).toEqual([]);
});

test('constructor scene and custom 3D receiver mount survive the manual mission launch',async({page,request})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const scene=await(await request.get('/api/preset/room')).json();scene.name='custom-room';scene.rx.mount_position=[.25,0,.8];
 expect((await request.post('/api/scene',{data:scene})).ok()).toBeTruthy();
 await page.goto('/experiments.html');
 await page.locator('#mission-select').selectOption('current');
 await expect(page.locator('#drive-mode')).toHaveValue('manual');
 await page.locator('#start-mission').click();
 await expect.poll(()=>page.evaluate(()=>window.experimentLab?.getState()?.experiment?.mode),{timeout:90000}).toBe('TELEOP');
 let state=await page.evaluate(()=>window.experimentLab.getState());
 expect(state.scenario.name).toBe('custom-room');expect(state.scenario.tx).toEqual(scene.tx);
 expect(state.scenario.rx.mount_position).toEqual([.25,0,.8]);expect(state.scenario.rx.mode).toBe('husky');
 const start=state.robot_pose.position;
 await page.locator('#viewport canvas').click();await page.keyboard.down('w');await page.waitForTimeout(2000);await page.keyboard.up('w');
 await page.waitForTimeout(700);state=await page.evaluate(()=>window.experimentLab.getState());
 expect(Math.hypot(...state.robot_pose.position.map((v,i)=>v-start[i]))).toBeGreaterThan(.1);
 const m=state.measurement;
 expect(Math.hypot(...m.position_m.map((v,i)=>v-m.robot_pose.position[i]))).toBeCloseTo(Math.hypot(.25,.8),4);
 await page.locator('#stop-mission').click();
 await expect.poll(()=>page.evaluate(()=>window.experimentLab.getState()?.experiment?.status)).toBe('CANCELLED');
 expect(errors).toEqual([]);
});
