# Embedding a forecast in the Squarespace site

The build publishes a scoped fragment for each region at:

```
https://eddie810.github.io/Sheerr-Weather-Forecasts/embed/region-avalon.html
```

It is a fragment, not a page: no `<html>`, no `<body>`, every selector scoped
under `.sw-forecast`, and typography inherited from the host so it matches the
surrounding page. GitHub Pages sends `access-control-allow-origin: *`, so a
browser on another domain may fetch it.

## Squarespace

Add a **Code Block** to the page (Business plan or higher) and paste:

```html
<div id="sw-avalon">Loading the Avalon forecast…</div>
<script>
  (function () {
    var target = document.getElementById('sw-avalon');
    var url = 'https://eddie810.github.io/Sheerr-Weather-Forecasts/embed/region-avalon.html';
    fetch(url, { cache: 'no-cache' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) { target.innerHTML = html; })
      .catch(function () {
        target.innerHTML = '<p>The forecast could not be loaded. ' +
          '<a href="' + url + '">Open it directly</a>.</p>';
      });
  })();
</script>
```

The forecast then refreshes with the daily build; the page itself needs no
further edits. The fallback matters: if the build or the network is down the
reader gets a link rather than an empty block.

## Alternatives

- **iframe** — `<iframe src="…/embed/region-avalon.html" style="width:100%;border:0"
  height="1400" title="Avalon forecast"></iframe>`. Works without a Code Block,
  but the height is fixed and will either clip or leave a gap.
- **Subdomain** — point `forecast.sheerrweather.ca` at GitHub Pages with a CNAME
  and serve the full pages directly, outside Squarespace.

## Other regions

Add the region to `config/locations.yml`, add a `type: region` page to
`config/site.yml`, and a matching fragment appears under `embed/`.
Set `embed: false` on a page to skip it.
