# Putting a forecast on the Squarespace site

**Do not paste the forecast HTML into a page.** Squarespace's editor strips
or rewrites `<style>` and `<link>` tags, which breaks both the forecast and
the surrounding layout. Paste one of the small snippets below instead; each
pulls the live forecast from this build.

The build publishes two files per region:

| File | For |
|---|---|
| `embed/region-avalon.html` | a fragment, fetched and injected |
| `embed/region-avalon-frame.html` | a standalone page, for an iframe |

Both live under `https://eddie810.github.io/Sheerr-Weather-Forecasts/`.

## Recommended: iframe (Code Block)

Nothing can leak in either direction, so Squarespace's CSS cannot affect the
forecast and the forecast cannot affect the page. The frame reports its own
height, so it grows when someone expands an alert rather than clipping.

```html
<iframe id="sw-forecast"
        src="https://eddie810.github.io/Sheerr-Weather-Forecasts/embed/region-avalon-frame.html"
        style="width:100%;border:0;display:block;height:1200px"
        scrolling="no" title="Avalon regional forecast"></iframe>
<script>
  window.addEventListener('message', function (e) {
    var h = e.data && e.data.sheerrForecastHeight;
    if (h) document.getElementById('sw-forecast').style.height = h + 'px';
  });
</script>
```

The `height:1200px` is only a starting value; the script replaces it once the
frame loads. Leave it in — if the script is ever blocked, the frame still
shows the forecast at a sensible height.

## Alternative: inject the fragment

Renders as part of the page rather than inside a frame, so it inherits the
site's fonts. More exposed to the theme's CSS, though the fragment scopes
everything under `.sw-forecast` and hardens its colours.

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

Both snippets need a **Code Block**, which Squarespace offers on Business
plans and above. On a lower plan, use an Embed Block with the iframe URL
directly — the height will be fixed, but it works.

## Other regions

Add the region to `config/locations.yml`, add a `type: region` page to
`config/site.yml`, and both files appear under `embed/` on the next build.
Set `embed: false` on a page to skip it.
