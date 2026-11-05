// Fixture app behaviour: reveal-on-scroll cards, cookie banner, an upgrade modal, a load-time POST
// (must be blocked by the capture browser) and an off-origin fetch (must be blocked too).
(function () {
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
  }, {threshold: 0.2});
  document.querySelectorAll('.reveal').forEach(function (el) { io.observe(el); });

  document.getElementById('cookie-accept').addEventListener('click', function () {
    document.getElementById('cookie-banner').remove();
  });
  document.getElementById('upgrade').addEventListener('click', function () {
    document.getElementById('modal').hidden = false;
  });
  document.getElementById('delete-all').addEventListener('click', function () {
    fetch('/api/notes', {method: 'DELETE'});
    document.getElementById('status').textContent = 'deleted';
  });
  fetch('/api/track', {method: 'POST', body: '{"event":"load"}'}).catch(function () {});
  fetch('https://api.example-cdn.test/ping').catch(function () {});
})();
