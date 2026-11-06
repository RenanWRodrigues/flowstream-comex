-- Regra: booking <= ETD < ETA e booking <= ATD < ATA; ATA só existe com ATD.
-- (A mesma regra de flowstream.domain.shipment.validate_timeline, agora no banco.)
select processo, booking_em, etd, eta, atd, ata
from {{ ref('int_embarque_timeline') }}
where etd < booking_em
    or eta <= etd
    or (atd is not null and atd < booking_em)
    or (ata is not null and atd is null)
    or (ata is not null and ata <= atd)
