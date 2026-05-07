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
6.  **Mesma Sala para Coortes (same_room_cohort — Passe 1):**
    *   Para cada coorte `c` (onde `same_room_cohort` não é `None`), seja `g_anchor` a primeira turma da coorte. Para cada outra turma `g_i ∈ c` e cada sala `r ∈ R`:
        `X[g_anchor, r] == X[g_i, r]`.
    *   Isso força todas as turmas da coorte a compartilharem exatamente o mesmo vetor de alocação de salas. Como a Restrição 1 garante que um grupo só pode estar em uma única sala, a igualdade acima assegura que todos os grupos da coorte ocupam a mesma sala.

**Função Objetivo (Minimizar Custo Total):**
*   Definimos o fator de prioridade `P[g]`:
    *   `P[g] = 1000` se `g.same_room_cohort` não for `None`.
    *   `P[g] = 1` caso contrário.
*   Custo de Grupos sem Sala (Prioridade Máxima): `C_u = Σ_g U[g] * config.unassigned_penalty * P[g]`.
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
1.  Para cada grupo `g ∈ G_unassigned` e cada `t ∈ T(g)`: O grupo deve receber exata 1 sala por horário: `Σ_r Y[g, t, r] <= 1`. (Se não for possível, deixar o grupo sem sugestão).
2.  Garantir o `AddNoOverlap` vinculando a nova variável `Y[g, t, r]` com os intervalos opcionais deste modelo secundário.

**Função Objetivo do Passe 2 (Maximizar Alocações):**
*   Definimos a recompensa base `reward_base` como um valor muito maior que qualquer custo de waste possível.
*   Para cada grupo `g`, a recompensa efetiva é `reward_g = reward_base * P[g]`, onde `P[g]` é o mesmo fator de prioridade absoluta do Passe 1 (`1000` para coortes, `1` caso contrário).
*   Custo a minimizar: `C = Σ_{g, t, r} Y[g, t, r] * (MAX(0, r.capacity - g.demand) * config.wasted_seats_weight - reward_g)`.
*   Como `reward_g` domina o termo de waste, o solver efetivamente maximiza o número de alocações, priorizando grupos de coorte.

**Nota sobre Coortes no Passe 2:**
A restrição de "mesma sala" é intencionalmente relaxada no Passe 2. Se uma coorte chegou ao Passe 2 como unassigned, isso é prova matemática de que não existe nenhuma sala viável para todos os seus horários simultaneamente. O Passe 2 atua como fallback de resgate com prioridade absoluta via `reward_g`.

**Output do Passe 2:**
*   As variáveis `Y` que forem resolvidas como verdadeiras serão colocadas no bloco `"suggestions"` do JSON de resposta (conforme API Contract). O sistema Laravel exibirá essas sugestões para o usuário.