# Modelo Matemático (UCTP com OR-Tools CP-SAT)

A alocação de salas é dividida em dois passes (Two-Pass Solver). O Passe 1 tenta a alocação rígida onde cada grupo fica integralmente em uma única sala. O Passe 2 pega as sobras e sugere quebras de horários.

## PASSE 1: Alocação Estrita (Strict Allocation)

**Conjuntos (Sets):**
*   `G`: Grupos (Turmas unitárias ou Fusões/Dobradinhas).
*   `R`: Salas (Rooms).
*   `T`: Horários (Timeslots).

**Variáveis de Decisão:**
*   `X[g, r] ∈ {0, 1}`: Variável booleana. Vale 1 se o grupo `g` é alocado inteiramente na sala `r`.
*   `U[g] ∈ {0, 1}`: Variável booleana. Vale 1 se o grupo `g` ficou SEM sala (Unassigned).

**Restrições Rígidas (Hard Constraints):**

1.  **Lógica de Atribuição Única:** 
    *   Para cada grupo `g ∈ G`: `Σ_r X[g, r] + U[g] == 1`. (Um grupo ou ganha exata 1 sala, ou fica unassigned).
2.  **Pré-alocação (Trava Manual):** 
    *   Se o grupo `g` possui `preassigned_room_id == r'`, forçar a restrição matemática: `X[g, r'] == 1`.
3.  **Conflitos de Horário (Timeline 1D e AddNoOverlap - CRÍTICO PARA PERFORMANCE):** 
    O solver NÃO deve usar restrições par a par O(N^2) para conflitos. Deve-se usar a feature nativa de Scheduling.
    *   *Passo A:* Converter os `timeslots` do Payload para uma linha do tempo contínua em minutos. Fórmula: `(DiaDaSemana * 1440) + (Hora * 60) + Minuto`. (Ex: Seg=0, Ter=1, Qua=2... Domingo=6).
    *   *Passo B:* Para cada grupo `g` e cada sala `r`, criar um `NewOptionalIntervalVar` onde os limites são as conversões do Passo A, e a presença (`is_present`) do intervalo está vinculada à variável `X[g, r]`. (Nota: Se o grupo possui múltiplos timeslots, criar múltiplos intervalos opcionais vinculados à mesma variável `X[g,r]`).
    *   *Passo C:* Para cada sala `r`, colocar todos os intervalos opcionais gerados para aquela sala em uma lista e aplicar `model.AddNoOverlap(intervalos_da_sala_r)`. 
4.  **Capacidade da Sala:** 
    *   Se `g.has_null_enrollment == False` e `X[g, r] == 1`:
        *   Se `config.strict_capacity == True`, garantir `r.capacity >= g.demand`.
        *   Se `config.strict_capacity == False`, a restrição é relaxada (permitindo aplicar margem estática de 1.2x ou flexibilização total).
5.  **Regra Bloco B (Pós-Graduação):** 
    *   Se `config.block_b_restriction_for_pos == True` e o grupo `g.tiptur == 'Pos Graduacao'` e o nome da sala `r` começar com a letra `B` (ex: `B09`), então `X[g, r] == 0`.

**Função Objetivo (Minimizar Custo Total):**
*   Custo de Grupos sem Sala (Prioridade Máxima): `C_u = Σ_g U[g] * config.unassigned_penalty`.
*   Custo de Desperdício de Assentos: `C_w = Σ_{g, r} X[g, r] * MAX(0, r.capacity - g.demand) * config.wasted_seats_weight`.
*   *Função a minimizar:* `C_total = C_u + C_w`.

---

## PASSE 2: Sugestão de Quebra de Horários (O 2º Passe)

Se, após otimizar o Passe 1, sobrarem grupos com `U[g] == 1` (ficaram de fora):

**Nova Configuração:**
*   Instanciar um NOVO modelo `CpModel`.
*   As alocações resolvidas no Passe 1 (`X[g,r] == 1`) devem ser inseridas neste novo modelo como `IntervalVar` fixos e permanentes nas salas, ocupando o tempo fisicamente (usando novamente o `AddNoOverlap`).

**Variáveis do Passe 2:**
*   Apenas os grupos que ficaram de fora (`G_unassigned`) participarão ativamente.
*   Criar nova variável `Y[g, t, r] ∈ {0, 1}`: 1 se o grupo `g` usará a sala `r` no timeslot específico `t`. (Aqui a regra da "sala única" é relaxada).

**Restrições do Passe 2:**
1.  Para cada grupo `g ∈ G_unassigned` e cada `t ∈ T(g)`: O grupo deve receber exata 1 sala por horário: `Σ_r Y[g, t, r] == 1`. (Se não for possível, deixar o grupo sem sugestão).
2.  Garantir o `AddNoOverlap` vinculando a nova variável `Y[g, t, r]` com os intervalos opcionais deste modelo secundário.

**Output do Passe 2:**
*   As variáveis `Y` que forem resolvidas como verdadeiras serão colocadas no bloco `"suggestions"` do JSON de resposta (conforme API Contract). O sistema Laravel exibirá essas sugestões para o usuário.