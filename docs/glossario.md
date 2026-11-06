# Glossário

Termos de comércio exterior e logística usados no projeto. As regras de validação dos
identificadores estão em [Regras dos identificadores](#regras-dos-identificadores), no fim
deste arquivo, e implementadas em `flowstream.domain`.

## Documentos de transporte

| Termo | Significado |
| --- | --- |
| **BL** (Bill of Lading) | Conhecimento de embarque marítimo: recibo da carga, contrato de transporte e título de propriedade. |
| **MBL** (Master BL) | BL emitido pelo armador ao agente de cargas (NVOCC), que aparece como embarcador. |
| **HBL** (House BL) | BL emitido pelo agente de cargas ao cliente final; vários HBLs podem estar sob um MBL (consolidação LCL). |
| **AWB** (Air Waybill) | Conhecimento aéreo. Número com 3 dígitos do prefixo da companhia + 8 dígitos, sendo o último um dígito verificador (módulo 7 dos 7 anteriores). |
| **MAWB / HAWB** | Master e House AWB, com a mesma lógica de MBL e HBL no modal aéreo. |
| **Commercial Invoice** | Fatura comercial do exportador: itens, valores, Incoterm e moeda. |
| **Packing List** | Romaneio: volumes, pesos (bruto e líquido) e dimensões da carga. |

## Carga e equipamentos

| Termo | Significado |
| --- | --- |
| **Contêiner** | Identificado pela ISO 6346: 3 letras do proprietário + categoria (`U`, `J` ou `Z`) + 6 dígitos de série + 1 dígito verificador. Ex.: `MSCU1234566`. |
| **TEU** | *Twenty-foot Equivalent Unit*: um contêiner de 20 pés. Unidade padrão de volume marítimo. |
| **FEU** | *Forty-foot Equivalent Unit*: um contêiner de 40 pés = 2 TEUs. |
| **FCL** | *Full Container Load*: o cliente usa o contêiner inteiro. |
| **LCL** | *Less than Container Load*: carga consolidada com a de outros clientes. |
| **CBM** | Metro cúbico, unidade de volume usada na cobrança de LCL. |
| **Isotanque** | Tanque dentro de uma armação de contêiner, para líquidos a granel. |

## Datas e prazos

| Termo | Significado |
| --- | --- |
| **ETD** | *Estimated Time of Departure*: data prevista de saída. |
| **ETA** | *Estimated Time of Arrival*: data prevista de chegada. |
| **ATD** | *Actual Time of Departure*: data real de saída. |
| **ATA** | *Actual Time of Arrival*: data real de chegada. |
| **Transit time** | Dias entre a saída e a chegada. |
| **Free time** | Dias livres concedidos pelo armador para usar o contêiner sem cobrança. |
| **Demurrage** | Cobrança por dia em que o contêiner fica no terminal além do free time (sobrestadia). |
| **Detention** | Cobrança por dia em que o contêiner fica fora do terminal (com o cliente) além do free time. |

## Comércio exterior e câmbio

| Termo | Significado |
| --- | --- |
| **PTAX** | Taxa de câmbio de referência divulgada diariamente pelo Banco Central do Brasil. |
| **NCM** | Nomenclatura Comum do Mercosul: código de 8 dígitos que classifica a mercadoria (ex.: `8471.30.12`). |
| **Incoterms** | Regras da Câmara de Comércio Internacional que definem responsabilidades e custos entre comprador e vendedor (ex.: FOB, CIF, EXW, DAP). |
| **OEA** | Operador Econômico Autorizado: certificação da Receita Federal para empresas de baixo risco, com despacho mais rápido. |

## Códigos padronizados

| Termo | Significado |
| --- | --- |
| **UN/LOCODE** | Código de 5 letras de localidades (2 do país + 3 do local). Ex.: `BRITJ` (Itajaí), `BRNVT` (Navegantes), `BRSSZ` (Santos). |
| **IATA** | Código de 3 letras de aeroportos. Ex.: `GRU`, `VCP`, `NVT`. |
| **ISO 4217** | Código de 3 letras de moedas. Ex.: `BRL`, `USD`, `EUR`, `CNY`. |
| **CNPJ** | Cadastro de pessoa jurídica: 14 caracteres, os 2 últimos verificadores; numérico ou, desde 07/2026, alfanumérico. Mascarado em todos os logs. |

## Regras dos identificadores

Implementadas em `flowstream/domain/identifiers.py` como tipos Pydantic (`ContainerNumber`,
`AirWaybill`, `NCM`, `CNPJ`, `UNLocode`, `IATACode`): todo dado que entra é **normalizado**
(maiúsculas, sem espaços nem pontuação) e **recusado** se a regra falhar. Nada é corrigido
por palpite.

### Contêiner — ISO 6346

| Parte | Formato | Exemplo (`CSQU3054383`) |
| --- | --- | --- |
| Proprietário | 3 letras (código BIC) | `CSQ` |
| Categoria | `U` (contêiner), `J` (equipamento destacável) ou `Z` (chassi) | `U` |
| Série | 6 dígitos | `305438` |
| Dígito verificador | 1 dígito | `3` |

Cálculo do dígito: cada letra vale um número (A=10, B=12, C=13… Z=38, pulando os múltiplos
de 11) e cada dígito vale ele mesmo; multiplica-se o valor de cada um dos 10 primeiros
caracteres por 2 elevado à sua posição (1, 2, 4, … 512), soma-se tudo, e o dígito é o resto
da divisão por 11 (resto 10 vira 0). Normalização aceita `CSQU 305438-3` → `CSQU3054383`.

### AWB — Air Waybill

`PPP-SSSSSSSS`: prefixo de 3 dígitos da companhia aérea + 8 dígitos de série. O último
dígito da série é o **resto da divisão por 7** dos 7 anteriores: em `020-12345675`,
1234567 mod 7 = 5. Normalizado para `PPP-SSSSSSSS`. As companhias do projeto são fictícias
e usam prefixos 901 a 906.

### NCM — Nomenclatura Comum do Mercosul

8 dígitos (`8471.30.12` → `84713012`): os 6 primeiros vêm do Sistema Harmonizado (capítulo,
posição, subposição) e os 2 últimos são do Mercosul. O capítulo (2 primeiros dígitos) vai
de 01 a 97, exceto o 77, reservado no Sistema Harmonizado. Zeros à esquerda são preservados
(`0201.30.00`, carne bovina).

### CNPJ — numérico e alfanumérico

14 caracteres: 8 da raiz, 4 do estabelecimento e 2 dígitos verificadores. Desde julho de
2026 a Receita Federal emite também **CNPJ alfanumérico**: as 12 primeiras posições podem ter
letras (`12.ABC.345/01DE-35`), e os 2 verificadores continuam numéricos.

Cálculo dos verificadores (módulo 11): cada caractere vale seu código ASCII menos 48 (dígitos
valem 0 a 9; A=17 … Z=42). O primeiro verificador usa os pesos 5,4,3,2,9,8,7,6,5,4,3,2 sobre
as 12 posições; o segundo usa 6,5,4,3,2,9,8,7,6,5,4,3,2 sobre as 12 posições mais o
primeiro verificador. Em cada um, resto menor que 2 vira 0; senão, 11 menos o resto. CNPJ
com todos os caracteres iguais é recusado. **Em logs, todo CNPJ é mascarado** como `[CNPJ]`.

> `00.000.000/0001-91` é um CNPJ real (Banco do Brasil): nunca use como exemplo fictício.

### UN/LOCODE e IATA

| Código | Formato | Exemplos |
| --- | --- | --- |
| UN/LOCODE | 2 letras do país (ISO 3166) + 3 letras ou dígitos de 2 a 9 | `BRITJ`, `CNSHA`, `NLRTM` |
| IATA (aeroporto) | 3 letras | `GRU`, `VCP`, `NVT` |

### Datas e valores

- **Datas** sempre com fuso horário; a referência é `America/Sao_Paulo` (UTC-3, sem horário
  de verão desde 2019). Data sem fuso é recusada, nunca "adivinhada".
- **Linha do tempo** de um embarque (`validate_timeline`): booking ≤ ETD < ETA e
  booking ≤ ATD < ATA; ATA exige ATD; ATD e ATA não podem estar no futuro. Atraso (ATD depois
  do ETD, ATA depois do ETA) **não** é violação: é informação para os KPIs.
- **Dinheiro** (`Money`) sempre em `Decimal` (float é recusado), em BRL, USD, EUR ou CNY.
  Somar moedas diferentes é erro. Conversão pela taxa com arredondamento bancário em 2 casas
  (meio vai para o par: 2,345 → 2,34; 2,355 → 2,36), que não acumula viés para cima.
