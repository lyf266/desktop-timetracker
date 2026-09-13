# Maintainer: lyf266 <https://github.com/lyf266>
pkgname=desktop-timetracker-git
pkgver=0.1.0
pkgrel=1
pkgdesc="Lightweight, zero-dependency, privacy-first desktop time tracker for KDE Plasma 6 Wayland"
arch=('any')
url="https://github.com/lyf266/desktop-timetracker"
license=('MIT')
depends=('python' 'qt6-tools' 'systemd')
makedepends=('git')
provides=('desktop-timetracker')
conflicts=('desktop-timetracker')
source=("$pkgname::git+https://github.com/lyf266/desktop-timetracker.git")
sha256sums=('SKIP')

package() {
    cd "$srcdir/$pkgname"
    install -Dm755 src/desktop-timetracker "$pkgdir/usr/bin/desktop-timetracker"
    ln -sf /usr/bin/desktop-timetracker "$pkgdir/usr/bin/timetrack"

    install -Dm644 src/timetracker_kwin.js "$pkgdir/usr/share/desktop-timetracker/timetracker_kwin.js"
    install -Dm644 config/rules.json.example "$pkgdir/usr/share/desktop-timetracker/rules.json.example"
    install -Dm644 systemd/desktop-timetracker.service "$pkgdir/usr/lib/systemd/user/desktop-timetracker.service"
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
    install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}
