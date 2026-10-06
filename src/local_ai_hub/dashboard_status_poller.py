"""Inline JavaScript for dashboard status polling."""

DASHBOARD_STATUS_POLLER_SCRIPT = r"""function createDashboardStatusPoller(poll,options={}){
  const baseDelay=Math.max(1,Number(options.baseDelay)||5000);
  const maxDelay=Math.max(baseDelay,Number(options.maxDelay)||60000);
  const maxFailures=Math.max(1,Math.ceil(Math.log2(maxDelay/baseDelay))+1);
  const isVisible=options.isVisible||(()=>document.visibilityState!=='hidden');
  const setTimer=options.setTimer||((fn,delay)=>setTimeout(fn,delay));
  const clearTimer=options.clearTimer||((id)=>clearTimeout(id));
  const random=options.random||Math.random;
  let timer=null,started=false,running=false,pending=false,visible=true,generation=0,failures=0;
  const current=token=>started&&visible&&isVisible()&&generation===token;
  function clear(){if(timer!==null){clearTimer(timer);timer=null}}
  function schedule(delay){clear();if(started&&visible&&isVisible())timer=setTimer(()=>{timer=null;void run()},delay)}
  async function run(){
    if(!started||!visible||!isVisible())return;
    if(running){pending=true;return}
    running=true;
    const token=generation;
    let succeeded=false;
    try{succeeded=await poll(()=>current(token))!==false}catch{}
    finally{
      running=false;
      if(current(token)){
        pending=false;
        failures=succeeded?0:Math.min(failures+1,maxFailures);
        const backoff=Math.min(maxDelay,baseDelay*2**Math.max(0,failures-1));
        const sample=Math.min(0.999999,Math.max(0,Number(random())||0));
        schedule(Math.min(maxDelay,Math.round(backoff*(0.8+sample*0.4))));
      }else if(pending&&started&&visible&&isVisible()){
        pending=false;
        schedule(0);
      }
    }
  }
  return{
    start(){if(started)return;started=true;visible=isVisible();generation++;schedule(0)},
    setVisible(next){visible=Boolean(next)&&isVisible();generation++;if(visible)schedule(0);else{pending=false;clear()}},
    refresh(){if(!started)return;generation++;failures=0;if(running){pending=true;return}schedule(0)},
    stop(){started=false;visible=false;pending=false;generation++;clear()}
  };
}
"""
