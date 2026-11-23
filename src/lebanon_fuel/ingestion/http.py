"""Sequential public HTTP requests; capture denials, never evade them."""
from dataclasses import dataclass
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import time
import httpx

AGENT = "LebanonFuelResearch/0.1 (public-price-research)"


class AccessStopped(RuntimeError):
    pass


@dataclass
class Fetch:
    response: httpx.Response
    capture_id: int


class PublicClient:
    def __init__(self, store, source, run, minimum_interval=3.0, transport=None):
        self.store,self.source,self.run=store,source,run
        self.interval=max(3.0,minimum_interval)
        timeout=store.config.get('collection',{}).get('request_timeout_seconds',30)
        self.client=httpx.Client(headers={"User-Agent":AGENT},timeout=timeout,follow_redirects=False,transport=transport)
        self.robots={}
        self.last={}

    def close(self):
        self.client.close()

    def _request(self, method, url, **kwargs):
        host=urlparse(url).netloc
        wait=self.interval-(time.monotonic()-self.last.get(host,0))
        if wait>0:
            time.sleep(wait)
        try:
            response=self.client.request(method,url,**kwargs)
        finally:
            self.last[host]=time.monotonic()
        headers={k:v for k,v in response.headers.items() if k in {"content-type","date","etag","last-modified","content-disposition","retry-after","location"}}
        cap=self.store.capture(self.source,str(response.url),response.content,response.headers.get("content-type","application/octet-stream"),self.run,response.status_code,{"method":method,"form":kwargs.get("data"),"headers":headers})
        return Fetch(response,cap)

    def fetch(self, url, method="GET", **kwargs):
        parsed=urlparse(url)
        if parsed.scheme!="https" or parsed.username or parsed.password:
            raise AccessStopped("Only public HTTPS source URLs are supported")
        origin=f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.robots:
            result=self._request("GET",origin+"/robots.txt")
            robot=RobotFileParser()
            if result.response.status_code==404:
                robot.parse(["User-agent: *", "Allow: /"])
            elif result.response.status_code==200 and "<html" not in result.response.text.lower():
                robot.parse(result.response.text.splitlines())
            else:
                raise AccessStopped("Cannot establish robots policy; use documented manual import")
            self.robots[origin]=robot
            self.interval=max(self.interval,float(robot.crawl_delay(AGENT) or robot.crawl_delay('*') or 0))
        if not self.robots[origin].can_fetch(AGENT,url):
            raise AccessStopped("Request denied by robots policy")
        result=self._request(method,url,**kwargs)
        response=result.response
        if response.status_code in {401,403,406,429}:
            raise AccessStopped(f"HTTP {response.status_code}; stopped without retry/bypass")
        if response.is_redirect:
            redirected=urljoin(url,response.headers.get("location",""))
            if urlparse(redirected).hostname!=parsed.hostname:
                raise AccessStopped("Cross-host redirect requires source investigation")
            raise AccessStopped(f"Redirect to {redirected}; use verified public page/manual import")
        response.raise_for_status()
        low=response.text[:5000].lower() if "text" in response.headers.get("content-type","") else ""
        if any(term in low for term in ("checking your browser","just a moment...","cf-chl-")):
            raise AccessStopped("Browser challenge detected; no automated bypass")
        return result
