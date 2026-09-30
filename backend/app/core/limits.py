"""Where every rate limit is set, and why.

Kept in one file on purpose. Limits scattered across routers are impossible to
review as a whole - you cannot tell what is unprotected without reading
everything - and these numbers are a security control, so they should be
auditable at a glance.

Each limit is sized by the harm it prevents, not by a uniform house style.
Reading a menu is cheap and gets a loose limit; sending an email costs money
and gets a tight one.
"""

from app.core.ratelimit import Limit

MINUTE = 60
HOUR = 60 * 60

# --- Login ------------------------------------------------------------------
# The per-address limits inside the OTP service (one code per minute, ten per
# hour, five guesses per code) stop an attacker working one account. These stop
# them working *many*: without a per-IP limit, one machine can spray a thousand
# addresses, and because each request sends a real email that is both an
# account-enumeration engine and a way to burn the Resend quota - which, once
# spent, locks every legitimate student out of logging in.
OTP_REQUEST_PER_IP = (Limit(5, MINUTE), Limit(30, HOUR))

# Guesses are already capped per code. This caps them per *machine*, so
# grinding many accounts in parallel is no faster than grinding one.
OTP_VERIFY_PER_IP = (Limit(10, MINUTE), Limit(60, HOUR))

# Stall signup, and much tighter than the customer route above, because the two
# are not the same kind of exposure. The customer route can only ever send mail
# to an @institute address, so its blast radius is the campus. This one accepts
# any address on the internet, which makes it a relay someone could aim at a
# stranger's inbox using our domain's reputation. A real stall owner signs up
# once, so there is no legitimate traffic to protect here.
VENDOR_OTP_REQUEST_PER_IP = (Limit(3, MINUTE), Limit(10, HOUR))
VENDOR_OTP_VERIFY_PER_IP = (Limit(10, MINUTE), Limit(40, HOUR))

# Unauthenticated and it hits the database on every call, so it is both a
# token-guessing surface and free load. No honest client refreshes this often.
TOKEN_REFRESH_PER_IP = (Limit(20, MINUTE),)

# A password is guessable in a way a random 6-digit code plus a 5-minute
# expiry is not, and this one opens the highest-privilege account in the
# system. Tight on purpose, and it fails closed: if Redis is unreachable the
# endpoint refuses rather than becoming unlimited.
ADMIN_LOGIN_PER_IP = (Limit(5, MINUTE), Limit(20, HOUR))

# --- Profile ----------------------------------------------------------------
PROFILE_READ = (Limit(120, MINUTE),)
PROFILE_WRITE = (Limit(20, MINUTE),)

# --- Orders -----------------------------------------------------------------
# The real damage case: a few hundred junk orders and the stall's tablet is
# useless during the lunch rush, which is an outage for that vendor even though
# every individual order was legitimate. Ten a minute is far above what a
# hungry person does and far below what hurts.
PLACE_ORDER = (Limit(10, MINUTE), Limit(40, HOUR))
CANCEL_ORDER = (Limit(20, MINUTE),)

# Tracking screens poll as well as holding a socket, so this stays roomy.
ORDER_READ = (Limit(120, MINUTE),)

# A vendor tapping through a lunch rush is fast, but not this fast.
ORDER_STATUS_UPDATE = (Limit(60, MINUTE),)

# Handing a delivery to a rider, or taking it yourself. Same shape as a status
# tap; a merchant reassigning a few times while working out who is free is
# normal.
ORDER_ASSIGN = (Limit(60, MINUTE),)

# --- Riders -----------------------------------------------------------------
# A rider's password is server-generated and readable - roughly 34 bits, which
# is deliberately not enough to stand on its own. This limit is the other half
# of that trade, so it is tight and it fails closed: an unreachable Redis must
# not turn rider sign-in into an unlimited guessing surface, the same reasoning
# as ADMIN_LOGIN_PER_IP.
RIDER_LOGIN_PER_IP = (Limit(5, MINUTE), Limit(30, HOUR))

# Creating riders, renaming them, regenerating a password. Each regenerate costs
# an scrypt hash, so this is not free work, but a merchant onboarding their crew
# does a handful in a sitting.
RIDER_WRITE = (Limit(20, MINUTE), Limit(100, HOUR))
RIDER_READ = (Limit(120, MINUTE),)

# What the rider app polls while on shift. Roomy on purpose - it is one small
# query and the app leans on it instead of holding a socket.
RIDER_ORDERS_READ = (Limit(120, MINUTE),)

# --- Vendors and menu -------------------------------------------------------
# Applications land in the admin's queue by hand, so spam here is spam at a
# person. Three an hour is plenty for someone fixing a typo in their stall name.
VENDOR_APPLY = (Limit(3, HOUR),)
VENDOR_UPDATE = (Limit(30, MINUTE),)
MENU_WRITE = (Limit(60, MINUTE), Limit(600, HOUR))

# Flipping dine-in, delivery and the delivery locations. A merchant working
# through a screen of switches taps quickly, and each tap is one write, so this
# sits well above human speed - the write is small and touches only their own
# stall.
FULFILMENT_READ = (Limit(60, MINUTE),)
FULFILMENT_WRITE = (Limit(60, MINUTE),)

# Public, unauthenticated, and the detail endpoint loads a whole menu per call -
# the cheapest way to put load on the database, and the obvious scraping target.
PUBLIC_BROWSE = (Limit(120, MINUTE), Limit(2000, HOUR))

# --- Media ------------------------------------------------------------------
# Each signature is a signed permit to upload to our Cloudinary account. Handing
# them out without limit means an authenticated user can fill the free tier and
# take image hosting down for every stall.
MEDIA_SIGNATURE = (Limit(20, MINUTE), Limit(100, HOUR))

# --- Admin ------------------------------------------------------------------
# Trusted, but a stolen admin token shouldn't be able to churn the whole vendor
# table in seconds.
ADMIN_READ = (Limit(120, MINUTE),)
ADMIN_WRITE = (Limit(60, MINUTE),)

# --- Realtime ---------------------------------------------------------------
# A ticket is what gets exchanged for a socket, so limiting tickets limits
# sockets at the source.
WS_TICKET = (Limit(30, MINUTE), Limit(300, HOUR))

# Handshakes are cheap to send and each one costs us a Redis pub/sub
# subscription, so reconnect storms are capped too.
WS_CONNECT_PER_IP = (Limit(60, MINUTE),)

# Concurrent live sockets per account. A tracking page and a vendor queue on a
# couple of devices is a handful; hundreds is someone exhausting our connections.
MAX_SOCKETS_PER_USER = 10

# --- Health -----------------------------------------------------------------
# /health is a bare liveness reply and stays unmetered. /health/ready queries
# Postgres and pings Redis on every call, so leaving it open would hand anyone
# an unauthenticated way to generate database load. Railway polls it about once
# a second during a deploy, so this is roughly double the headroom it needs -
# generous on purpose, because throttling a platform healthcheck would read as
# a dead service and roll the release back.
HEALTH_READY = (Limit(120, MINUTE),)
