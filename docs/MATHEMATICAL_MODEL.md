# Modelo Matemático (UCTP com OR-Tools CP-SAT)

O solver resolve o problema de alocação de salas em um único passo, usando a
variável de decisão `Y[g, t, r]`. Essa variável indica que o grupo `g` utiliza
a sala `r` no horário `t`, permitindo que uma mesma turma ocupe salas distintas
em horários diferentes (*split class*).

## Conjuntos (Sets)

*   `G`: Grupos (Turmas unitárias ou Fusões/Dobradinhas).
*   `R`: Salas (Rooms).
*   `T(g)`: Horários (Timeslots) do grupo `g`.

## Variáveis de Decisão

*   `Y[g, t, r] ∈ {0, 1}`: 1 se o grupo `g` utiliza a sala `r` no horário `t`.
*   `V[g, t] ∈ {0, 1}`: 1 se o horário `t` do grupo `g` ficou sem sala.

## Restrições Rígidas (Hard Constraints)

1.  **Atribuição Única por Horário:**
    *   Para cada grupo `g ∈ G` e cada horário `t ∈ T(g)`:
        `Σ_r Y[g, t, r] + V[g, t] == 1`.
    *   Todo horário é ou alocado em exatamente uma sala ou fica explicitamente
        sem sala.

2.  **Pré-alocação (Trava Manual):
    *   Se o grupo `g` possui `preassigned_room_id == r'`, forçar:
        `Y[g, t, r'] == 1` para todo `t ∈ T(g)`.

4.  **Salas Bloqueadas para Distribuição Automática:**
    *   Se `g.preassigned_room_id is None` e `r.available_for_auto == False`,
        então `Y[g, t, r] == 0` para todo `t`.

5.  **Conflitos de Horário (Timeline 1D e AddNoOverlap - CRÍTICO PARA PERFORMANCE):**
    *   O solver NÃO usa restrições par a par O(N^2) para conflitos. Usa a
        feature nativa de Scheduling.
    *   *Passo A:* Converter os `timeslots` do Payload para uma linha do tempo
        contínua em minutos: `(DiaDaSemana * 1440) + (Hora * 60) + Minuto`.
        (Ex: Seg=0, Ter=1, Qua=2... Domingo=6).
    *   *Passo B:* Para cada `(g, t, r)`, criar um `NewOptionalIntervalVar`
        onde os limites são as conversões do Passo A e a presença está vinculada
        a `Y[g, t, r]`.
    *   *Passo C:* Para cada sala `r`, aplicar `model.AddNoOverlap(intervalos_da_sala_r)`.

6.  **Capacidade da Sala:**
    *   Se `g.has_null_enrollment == False` e a sala não é a pré-alocada:
        *   Se `config.strict_capacity == True`, garantir `r.capacity >= g.demand`
            (`Y[g, t, r] == 0` caso contrário).
        *   Se `config.strict_capacity == False`, a restrição é relaxada e o
            solver pode alocar mesmo com capacidade insuficiente, pagando
            penalidades na função objetivo.

7.  **Regra do Bloco B (Pós-Graduação):**
    *   Se `config.block_b_restriction_for_pos == True`, `g.tiptur == 'Pos Graduacao'`
        e o nome da sala `r` começar com `B` (ex: `B09`), então
        `Y[g, t, r] == 0` para todo `t` (exceto pré-alocação).

8.  **Proteção de Calouros no Bloco A:**
    *   Se `config.block_a_restriction_for_freshmen == True`, `g.is_freshmen == True`
        e o nome da sala `r` começar com `A`, então `Y[g, t, r] == 0` para todo `t`
        (exceto pré-alocação).

## Soft Constraints e Função Objetivo

### Fatores de Prioridade

*   `P[g] = 1000` se `g.same_room_cohort` não for `None`.
*   `P[g] = 1` caso contrário.

### 1. Horários Sem Sala (Unassigned)

A penalidade `config.unassigned_penalty` é distribuída entre os horários do
grupo, de forma que deixar **todos** os horários de um grupo sem sala custe
pelo menos essa penalidade:

*   `slot_unassigned_penalty = ceil(config.unassigned_penalty / max_ts)`,
    onde `max_ts = max_g |T(g)|`.

`C_u = Σ_{g, t} V[g, t] * slot_unassigned_penalty * P[g]`

### 2. Divisão de Turmas (Split Class)

Para cada grupo `g`:

*   `Z_class[g, r] ∈ {0, 1}`: vale 1 se o grupo `g` utiliza a sala `r` em algum horário.
    *   `Z_class[g, r] >= Y[g, t, r]` para todo `t ∈ T(g)`.
    *   `Z_class[g, r] <= Σ_{t ∈ T(g)} Y[g, t, r]`.
*   `num_rooms_class[g] = Σ_r Z_class[g, r]`.
*   `extra_class[g] = max(0, num_rooms_class[g] - 1)`:
    *   `extra_class[g] >= num_rooms_class[g] - 1`
    *   `extra_class[g] >= 0`

`C_split_class = Σ_g extra_class[g] * config.split_class_penalty`

### 3. Divisão de Coortes (Split Cohort)

Para cada coorte `c` (onde `same_room_cohort` não é `None`), seja `members(c)` o
conjunto de grupos pertencentes a `c`.

*   `Z[c, r] ∈ {0, 1}`: vale 1 se **algum** grupo do coorte `c` utilizar a sala `r`.
    *   `Z[c, r] >= Y[g, t, r]` para todo `g ∈ members(c)`, `t ∈ T(g)`.
    *   `Z[c, r] <= Σ_{g ∈ members(c), t ∈ T(g)} Y[g, t, r]`.
*   `num_rooms_used[c] = Σ_r Z[c, r]`.
*   `extra_rooms[c] = max(0, num_rooms_used[c] - 1)`.

`C_split_cohort = Σ_c extra_rooms[c] * config.split_cohort_penalty`

### 4. Ocupação Piecewise de Salas

Para cada `Y[g, t, r] == 1`:

*   `free_seats = r.capacity - g.demand`
*   `free_seats_min = r.capacity * config.comfort_zone_min_percent / 100`
*   `free_seats_max = r.capacity * config.comfort_zone_max_percent / 100`
*   Se `free_seats < free_seats_min`:
    *   `excess = MAX(0, g.demand - (r.capacity - free_seats_min))`
    *   custo = `excess * config.claustrophobia_penalty`
*   Se `free_seats > free_seats_max`:
    *   `excess = MAX(0, (r.capacity - free_seats_max) - g.demand)`
    *   custo = `excess * config.waste_penalty`
*   Caso contrário (zona de conforto): custo = 0.

`C_piecewise = Σ_{g, t, r} Y[g, t, r] * piecewise(g, r)`

### 5. Penalidades Direcionais

*   Graduação no Bloco A: `Y[g, t, r] * config.undergrad_in_block_a_penalty`.
*   Pós-Graduação no Bloco B: `Y[g, t, r] * config.pos_in_block_b_penalty`.

`C_directional = Σ_{g, t, r} Y[g, t, r] * directional_penalty(g, r)`

### Função Objetivo

Minimizar:

`C_total = C_u + C_split_class + C_split_cohort + C_piecewise + C_directional`

## Mapeamento do Resultado para o JSON de Resposta

Após a otimização, as variáveis `Y[g, t, r]` são lidas e convertidas para o
contrato da API:

*   **Turma 100% alocada em uma única sala** (todos os horários alocados e
    mesma sala para todos): entra em `allocations` como `{group_id, room_id}`.
*   **Turma dividida entre salas** ou **parcialmente sem sala**: o `group_id`
    entra em `unassigned_groups` e cada par `(timeslot_id, room_id)` alocado
    vira uma entrada em `suggestions`.
*   **Turma totalmente sem sala**: o `group_id` entra em `unassigned_groups` e
    não gera `suggestions`.

A prioridade absoluta de coortes é preservada porque o fator `P[g]` multiplica
 também a penalidade por horário sem sala.
