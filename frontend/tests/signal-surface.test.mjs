import {test} from 'node:test';
import assert from 'node:assert/strict';
import {signalHeight,signalSurface} from '../src/signal-surface.js';
const cell=(x,y,rssi,z=.83)=>({position_m:[x,y,z],mean_dbm:rssi});
const square=[cell(0,0,-100),cell(1,0,-80),cell(1,1,-40),cell(0,1,-20)];

test('RSSI graph height is monotone and bounded independently of physical antenna Z',()=>{
 assert(signalHeight(-40)>signalHeight(-80));assert.equal(signalHeight(-140),signalHeight(-100));
 assert.equal(signalHeight(0),signalHeight(-20));
 const mesh=signalSurface(square);assert.equal(mesh.triangles,2);assert.equal(mesh.antenna_z_m,.83);
 assert(mesh.positions.every(Number.isFinite));assert.equal(Math.max(...mesh.positions.filter((v,i)=>i%3===2)),5.08);
});
test('missing returns and isolated measurements never invent a complete field',()=>{
 assert.equal(signalSurface([cell(0,0,null),cell(1,0,NaN)]).triangles,0);
 assert.equal(signalSurface([square[0],square[2]]).triangles,0);
 assert.equal(signalSurface(square.map((c,i)=>i===2?{...c,mean_dbm:null}:c)).triangles,1);
});
test('surface does not bridge a thin wall between valid samples',()=>{
 const wall={center:[.5,.5,1],size:[.1,3,2],yaw_rad:0};
 assert.equal(signalSurface(square,1,5,[wall]).triangles,0);
 const overhead={...wall,center:[.5,.5,5]};assert.equal(signalSurface(square,1,5,[overhead]).triangles,2);
});
test('separated grid areas and different physical heights are never stitched together',()=>{
 const far=square.map(c=>({...c,position_m:[c.position_m[0]+10,c.position_m[1],.83]}));
 assert.equal(signalSurface([...square,...far]).triangles,4);
 const higher=square.map(c=>({...c,mean_dbm:-30,position_m:[...c.position_m.slice(0,2),1.8]}));
 assert.deepEqual(signalSurface([...square,...higher]).positions,signalSurface(square).positions);
});
