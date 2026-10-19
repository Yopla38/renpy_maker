# Généré par renpy_maker : ne pas éditer à la main, modifier l'histoire puis réexporter.

define c_eve = Character("Eve")
define c_pierre = Character("Pierre")

image s1_p8 = Transform("images/s1_p8.png", xysize=(1920, 1080), fit="cover")
image s1_p1 = Transform("images/s1_p1.png", xysize=(1920, 1080), fit="cover")
image s1_p2 = Transform("images/s1_p2.png", xysize=(1920, 1080), fit="cover")
image s1_p3 = Transform("images/s1_p3.png", xysize=(1920, 1080), fit="cover")
image s1_p4 = Transform("images/s1_p4.png", xysize=(1920, 1080), fit="cover")
image s1_p5 = Transform("images/s1_p5.png", xysize=(1920, 1080), fit="cover")
image s1_p6 = Transform("images/s1_p6.png", xysize=(1920, 1080), fit="cover")
image s1_p7 = Transform("images/s1_p7.png", xysize=(1920, 1080), fit="cover")
image s2_p1 = Transform("images/s2_p1.png", xysize=(1920, 1080), fit="cover")
image s2_p2 = Transform("images/s2_p2.png", xysize=(1920, 1080), fit="cover")
image s2_p3 = Transform("images/s2_p3.png", xysize=(1920, 1080), fit="cover")
image s2_p4 = Transform("images/s2_p4.png", xysize=(1920, 1080), fit="cover")
image s2_p5 = Transform("images/s2_p5.png", xysize=(1920, 1080), fit="cover")
image s2_p6 = Transform("images/s2_p6.png", xysize=(1920, 1080), fit="cover")
image s2_p8 = Transform("images/s2_p8.png", xysize=(1920, 1080), fit="cover")
image s2_p7 = Transform("images/s2_p7.png", xysize=(1920, 1080), fit="cover")
image s3_p1 = Transform("images/s3_p1.png", xysize=(1920, 1080), fit="cover")
image s3_p2 = Transform("images/s3_p2.png", xysize=(1920, 1080), fit="cover")
image s3_p3 = Transform("images/s3_p3.png", xysize=(1920, 1080), fit="cover")
image s3_p4 = Transform("images/s3_p4.png", xysize=(1920, 1080), fit="cover")
image s3_p5 = Transform("images/s3_p5.png", xysize=(1920, 1080), fit="cover")
image s3_p6 = Transform("images/s3_p6.png", xysize=(1920, 1080), fit="cover")
image s3_p7 = Transform("images/s3_p7.png", xysize=(1920, 1080), fit="cover")

label start:
    jump s1

label s1:
    # Une traite matinale
    scene s1_p8 with dissolve
    "Les premières lueurs du jour glissent entre les planches de l'étable et dorent la poussière en suspension. Une odeur de foin tiède et de lait frais flotte dans l'air."  # expression : calme
    scene s1_p1 with dissolve
    c_eve "(elle fredonne, le front appuyé contre le flanc d'une vache) Mmh mm mmh... Voilà, ma belle, doucement..."  # expression : sourire paisible
    scene s1_p2 with dissolve
    c_eve "Toi, Marguerite, tu es toujours la plus généreuse. Si toutes tes copines avaient ton courage, je serais déjà au lit !"  # expression : sourire taquin
    scene s1_p3 with dissolve
    "Eve s'étire en grimaçant, une main dans le creux des reins. Ses yeux sont cernés, mais un petit sourire fier ne la quitte pas."  # expression : fatigue
    scene s1_p4 with dissolve
    c_eve "Ne fais pas cette tête, Noiraude. Je sais que tu aimes les caresses avant la traite. Tiens... là, derrière l'oreille. Voilà, tu ronronnerais presque !"  # expression : tendresse
    scene s1_p5 with dissolve
    "Un meuglement satisfait lui répond. Eve éclate de rire et sa voix résonne sous la charpente."  # expression : rire
    c_eve "(elle jette un coup d'œil vers le fond de l'étable) Attends... Les bidons sont déjà presque pleins ? Et il n'est même pas encore sept heures !"  # expression : surprise
    scene s1_p6 with dissolve
    c_eve "Eh bien, mesdames, on a cinq minutes d'avance. Je crois que ça mérite un petit morceau de pain sec pour tout le monde."  # expression : fierté
    "Elle essuie ses mains sur son tablier et rejette en arrière une mèche blonde échappée de sa tresse. Dehors, le soleil monte doucement sur la cour de la ferme."  # expression : sérénité
    scene s1_p7 with dissolve
    c_eve "Ce sera une belle journée, je le sens. Allez, on termine tranquillement, et ensuite... un bon café, enfin."  # expression : sourire rêveur

label s2:
    # Le voisin en avance
    scene s2_p1 with dissolve
    "Un grincement retentit : la grande porte de l'étable s'ouvre sur une silhouette à contre-jour. Pierre s'avance, une caisse de bidons vides sous le bras, et s'arrête net en apercevant Eve."  # expression : surprise
    scene s2_p2 with dissolve
    c_pierre "Oh... Bonjour. Je pensais trouver tes parents. Je suis venu pour le lait, comme d'habitude."  # expression : surpris
    scene s2_p3 with dissolve
    c_eve "Tu es en avance, voisin. Mes parents sont partis au marché, tu vas devoir te contenter de moi."  # expression : sourire taquin
    scene s2_p4 with dissolve
    c_pierre "Ce n'est pas un problème, au contraire, je voulais dire... enfin, je ne voulais pas te déranger pendant que tu..."  # expression : gêné
    scene s2_p5 with dissolve
    "Pierre recule d'un pas pour s'excuser et son talon heurte un seau. Il vacille, agite les bras et rattrape de justesse la caisse avant de retrouver l'équilibre."  # expression : maladroit
    c_eve "Attention, le seau est de leur côté, pas du tien ! Il ne t'a rien fait, pourtant."  # expression : rire
    c_pierre "Il m'a tendu une embuscade. Je suis un homme courageux, mais je n'avais pas prévu d'affronter un seau dès le matin."  # expression : sourire amusé
    scene s2_p6 with dissolve
    c_eve "Eh bien, tu t'en sors avec les honneurs. Je m'appelle Eve, au fait. On se croise depuis des mois, mais on ne s'est jamais vraiment parlé."  # expression : sourire
    scene s2_p8 with dissolve
    c_pierre "Pierre. Enchanté, Eve. Et pardon pour cette entrée en scène, je n'ai pas l'habitude de faire un tel numéro."  # expression : sourire timide
    scene s2_p7 with dissolve
    c_eve "Ne t'excuse pas, c'était la meilleure chose qui me soit arrivée ce matin. Viens, le lait est presque prêt. Et il reste du café, si tu veux."  # expression : sourire chaleureux

label s3:
    # Les bidons de lait
    scene s3_p1 with dissolve
    "Dans la cour, le soleil du matin chauffe déjà les pavés. Eve fait rouler un premier bidon de lait jusqu'à la camionnette de Pierre, garée devant l'étable."  # expression : neutre
    scene s3_p2 with dissolve
    c_eve "Attention, celui-là est plein à ras bord. Tu le prends par l'anse, sinon tu vas encore en mettre partout."  # expression : sourire moqueur
    c_pierre "Je vais essayer de ne pas battre mon record de maladresse du jour. Dis-moi, tu fais tout ça toute seule, d'habitude ?"  # expression : amusé
    scene s3_p3 with dissolve
    c_eve "Avec mes parents, oui. Mais ce matin, ils sont au marché. Et toi, ta ferme, ça donne quoi ? Je ne sais même pas combien de bêtes tu as."  # expression : curiosité
    scene s3_p4 with dissolve
    c_pierre "Une vingtaine de vaches et quelques hectares de prairie. Le plus dur, c'est de tenir avec les prix du lait. Chaque mois, je refais mes comptes en croisant les doigts."  # expression : soucieux
    scene s3_p5 with dissolve
    c_eve "Ah, ça, je connais. Mon père passe ses soirées sur ses factures en soupirant. Moi, je rêve d'un jour où on pourrait vendre notre fromage directement, sans intermédiaire."  # expression : rêveuse
    scene s3_p6 with dissolve
    c_pierre "Sérieusement ? J'y pense depuis des années ! Une petite fromagerie, un panneau au bord de la route... Je n'en ai jamais parlé à personne."  # expression : surpris
    c_eve "Alors nous voilà deux fous. C'est étrange, on vit à deux pas l'un de l'autre et on découvre ça seulement aujourd'hui."  # expression : sourire sincère
    scene s3_p7 with dissolve
    "Pierre referme les portes de la camionnette. Il hésite un instant, la main sur la poignée, comme s'il n'osait pas partir."  # expression : hésitation
    c_pierre "La semaine prochaine, je pourrais passer un peu plus tôt. Pour t'aider avec la traite, et pour qu'on continue de parler de nos projets."  # expression : timide
    c_eve "Avec plaisir. Viens dès l'aube si tu veux, je mettrai le café à chauffer."  # expression : grand sourire
    return

