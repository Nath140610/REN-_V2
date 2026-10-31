const assert = require('node:assert/strict');
const {classify, detect} = require('../rene/static/device.js');

const chromeTab = 'Mozilla/5.0 (Linux; Android 15; SM-X700 Build/ABC) AppleWebKit/537.36 Chrome/141 Safari/537.36';
const samsungTab = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 SamsungBrowser/24 Chrome/117 Safari/537.36';
assert.equal(classify(chromeTab).supported, true);
assert.equal(classify(samsungTab).supported, true);
assert.equal(classify('Mozilla/5.0 (Linux; Android 13; SM-X706B) Chrome/128 Mobile Safari/537.36').supported, true);
assert.equal(classify('Mozilla/5.0 (Linux; Android 15; SM-S921B) Chrome/141 Mobile Safari/537.36').supported, false);
assert.equal(classify('Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141').reason, 'windows');
assert.equal(classify('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)').reason, 'apple');
assert.equal(classify('Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)').reason, 'apple');
assert.equal(classify('Mozilla/5.0 (Linux; Android 15; Pixel Tablet) Chrome/141 Safari/537.36').supported, false);

detect({userAgent:'Mozilla/5.0 (Linux; Android 10; K) Chrome/141 Safari/537.36',
  userAgentData:{platform:'Android',mobile:false,getHighEntropyValues:async()=>({model:'SM-X710',platform:'Android'})}
}).then(result=>{assert.equal(result.supported,true);console.log('Détection des appareils : OK')}).catch(error=>{console.error(error);process.exitCode=1});
