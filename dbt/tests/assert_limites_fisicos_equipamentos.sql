-- Regra: peso dentro do limite físico de cada equipamento (carga máxima aproximada):
-- 20DV 28.000 kg, 40HC 26.500 kg, ISO20 26.000 kg. Achado da auditoria de dados do P03.
select processo, container_numero, tipo, peso_kg
from {{ ref('stg_equipamentos') }}
where peso_kg <= 0
    or (tipo = '20DV' and peso_kg > 28000)
    or (tipo = '40HC' and peso_kg > 26500)
    or (tipo = 'ISO20' and peso_kg > 26000)
