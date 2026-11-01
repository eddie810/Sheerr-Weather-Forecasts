const { chromium } = require('playwright');
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:1920,height:1080}});
await p.goto('file://'+process.argv[2]);await p.waitForTimeout(2500);
await (await p.$('#graphic')).screenshot({path:process.argv[3]});await b.close();})();
