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
image s4_p1 = Transform("images/s4_p1.png", xysize=(1920, 1080), fit="cover")
image s4_p2 = Transform("images/s4_p2.png", xysize=(1920, 1080), fit="cover")
image s4_p3 = Transform("images/s4_p3.png", xysize=(1920, 1080), fit="cover")
image s4_p4 = Transform("images/s4_p4.png", xysize=(1920, 1080), fit="cover")
image s4_p5 = Transform("images/s4_p5.png", xysize=(1920, 1080), fit="cover")
image s4_p6 = Transform("images/s4_p6.png", xysize=(1920, 1080), fit="cover")
image s4_p7 = Transform("images/s4_p7.png", xysize=(1920, 1080), fit="cover")
image s4_p8 = Transform("images/s4_p8.png", xysize=(1920, 1080), fit="cover")
image s4_p10 = Transform("images/s4_p10.png", xysize=(1920, 1080), fit="cover")
image s4_p11 = Transform("images/s4_p11.png", xysize=(1920, 1080), fit="cover")
image s4_p12 = Transform("images/s4_p12.png", xysize=(1920, 1080), fit="cover")
image s5_p1 = Transform("images/s5_p1.png", xysize=(1920, 1080), fit="cover")
image s5_p2 = Transform("images/s5_p2.png", xysize=(1920, 1080), fit="cover")
image s5_p3 = Transform("images/s5_p3.png", xysize=(1920, 1080), fit="cover")
image s5_p5 = Transform("images/s5_p5.png", xysize=(1920, 1080), fit="cover")
image s5_p4 = Transform("images/s5_p4.png", xysize=(1920, 1080), fit="cover")
image s5_p6 = Transform("images/s5_p6.png", xysize=(1920, 1080), fit="cover")
image s6_p1 = Transform("images/s6_p1.png", xysize=(1920, 1080), fit="cover")
image s6_p2 = Transform("images/s6_p2.png", xysize=(1920, 1080), fit="cover")
image s6_p3 = Transform("images/s6_p3.png", xysize=(1920, 1080), fit="cover")
image s6_p4 = Transform("images/s6_p4.png", xysize=(1920, 1080), fit="cover")
image s6_p5 = Transform("images/s6_p5.png", xysize=(1920, 1080), fit="cover")
image s6_p7 = Transform("images/s6_p7.png", xysize=(1920, 1080), fit="cover")
image s6_p6 = Transform("images/s6_p6.png", xysize=(1920, 1080), fit="cover")
image s6_p8 = Transform("images/s6_p8.png", xysize=(1920, 1080), fit="cover")
image s6_p9 = Transform("images/s6_p9.png", xysize=(1920, 1080), fit="cover")
image s6_p10 = Transform("images/s6_p10.png", xysize=(1920, 1080), fit="cover")

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

label s4:
    # Une tenue inhabituelle
    scene s4_p1 with dissolve
    "Le soleil de fin de matinée écrase le grand pré. Pierre s'est garé devant la ferme plus tôt que jamais, mais l'étable est vide. Le père d'Eve, en train de réparer une clôture, lève le menton vers le fond du sentier : « Elle est dans les champs, va donc la voir. »"  # expression : neutre
    scene s4_p2 with dissolve
    "Pierre s'engage sur le sentier bordé d'herbes hautes. Au bout du chemin, une silhouette se découpe dans la lumière : Eve, les cheveux blonds dénoués, une jupe légère qui danse autour de ses genoux au gré de la brise."  # expression : émerveillé
    scene s4_p3 with dissolve
    c_pierre "Eve... je... enfin, bonjour. Tu... c'est... Il y a du vent aujourd'hui, non ?"  # expression : gêné, bafouillant
    scene s4_p4 with dissolve
    "Eve l'a vu arriver de loin, mais elle se redresse lentement, une main sur la hanche, comme si de rien n'était. Un sourire en coin lui échappe malgré elle."  # expression : sourire en coin
    scene s4_p5 with dissolve
    c_eve "Tu es en avance, encore. Tu fais exprès, ou tu ne sais simplement pas lire l'heure ?"  # expression : taquine
    scene s4_p6 with dissolve
    with Pause(1.0)
    scene s4_p7 with dissolve
    with Pause(1.0)
    scene s4_p8 with dissolve
    c_pierre "Je t'avais dit que je viendrais plus tôt. Je ne pensais pas... te trouver dans un endroit aussi... enfin, aussi joli. Le pré, je veux dire. Le pré est très joli."  # expression : rougissant
    scene s4_p10 with dissolve
    c_eve "Le pré, bien sûr. Il a de la chance de te plaire autant. Moi, j'ai simplement pensé que les vaches méritaient un peu d'élégance, aujourd'hui."  # expression : amusée
    scene s4_p11 with dissolve
    c_pierre "Les vaches ont bon goût, alors. Et moi aussi, apparemment, puisque je suis encore là à raconter n'importe quoi."  # expression : rire gêné
    scene s4_p12 with dissolve
    "Eve éclate de rire, d'un rire clair qui envole quelques oiseaux des herbes. Elle désigne du menton le grand chêne, un peu plus loin, dont l'ombre s'étend sur le pré."  # expression : rieuse
    c_eve "Viens, ramasse ton courage et suis-moi. Il y a de l'ombre là-bas, et j'ai apporté de l'eau fraîche. Tu me raconteras tes projets... et peut-être pourquoi tu perds tes mots."  # expression : complice

label s5:
    # La clôture à réparer
    scene s5_p1 with dissolve
    "Ils n'ont pas fait dix pas vers le chêne qu'Eve s'arrête net devant la clôture, où un fil pend mollement entre deux piquets. Elle porte la main à sa bouche, l'air faussement catastrophé."  # expression : surprise feinte
    c_eve "Oh non, regarde ça ! Le fil a lâché. Si les vaches passent par là, mon père va me faire une scène. Tu pourrais m'aider cinq minutes, Pierre ? Ça tombe bien, tu as l'air d'avoir de bons bras."  # expression : espiègle
    c_pierre "Cinq minutes... oui, bien sûr. Enfin, je ne suis pas un expert en clôtures, mais je peux tenir un fil. Je crois."  # expression : gêné
    scene s5_p2 with dissolve
    "Il attrape le fil et tire de toutes ses forces. Eve se place tout près de lui pour tenir l'autre extrémité. Son regard s'attarde sur lui un peu trop longtemps, et le vent soulève sa jupe légère, qui danse autour de ses genoux."  # expression : malicieuse
    scene s5_p3 with dissolve
    with Pause(1.0)
    scene s5_p5 with dissolve
    c_eve "Tu tires dans le mauvais sens, tu sais. À moins que tu veuilles aussi réparer la clôture du voisin ?"  # expression : sourire en coin
    c_pierre "Ah ! Non, pardon, c'est que... le vent, la jupe... je veux dire, la clôture ! Le vent dans la clôture, c'est pénible, ça m'a distrait."  # expression : rouge de confusion
    scene s5_p4 with dissolve
    "Il lâche le fil, qui lui claque contre la main. Il pousse un petit cri, secoue ses doigts, et Eve éclate de rire, pliée en deux contre un piquet."  # expression : hilare
    c_eve "Tu es adorable quand tu rougis. Et tu es un très mauvais menteur, Pierre. Tu sais que cette clôture n'a jamais été cassée, n'est-ce pas ?"  # expression : regard franc
    c_pierre "Je m'en doutais, oui. Elle est plus solide que moi. Mais je n'ai rien dit, parce que... je n'avais pas envie de partir."  # expression : sourire timide
    scene s5_p6 with dissolve
    "Leurs rires se mêlent un instant dans le vent. Aucun des deux ne cherche plus à faire semblant, et le silence qui suit n'a rien de gênant."  # expression : complices
    c_eve "Alors reste. Et samedi soir, au lieu de réparer des clôtures qui n'existent pas, tu pourrais m'inviter à dîner. Pour de vrai, cette fois."  # expression : sourire tendre

label s6:
    # Sous le grand chêne
    scene s6_p1 with dissolve
    "La chaleur monte sur la colline. Sous le grand chêne, l'ombre est fraîche et les feuilles bruissent doucement. Eve pose son panier dans l'herbe et en sort du pain, un morceau de fromage et une bouteille de limonade encore humide."  # expression : calme
    scene s6_p2 with dissolve
    c_eve "Voilà, mon grand stratagème pour te garder ici. Du pain de ce matin, du fromage de la ferme, et de la limonade de ma mère. Personne n'a jamais résisté à sa limonade."  # expression : sourire taquin
    c_pierre "Alors je suis fichu. Je n'avais déjà pas beaucoup de volonté, et là, tu sors l'artillerie lourde."  # expression : sourire gêné
    scene s6_p3 with dissolve
    "Ils s'installent dos au tronc, épaule contre épaule sans vraiment l'avoir décidé. En contrebas, les vaches ne sont plus que des taches pâles dans les prés."  # expression : douceur
    scene s6_p4 with dissolve
    c_pierre "Quand j'étais petit, je voulais partir loin, voir la mer, les grandes villes. Et maintenant, je regarde cette vallée et je me dis que je ne voudrais être nulle part ailleurs."  # expression : rêveur
    scene s6_p5 with dissolve
    c_eve "Moi, je rêve d'agrandir le troupeau, de faire mon propre fromage, peut-être d'ouvrir un petit stand au marché. Rien de grandiose. Mais ici, le matin, quand la brume se lève sur les champs, j'ai l'impression que le monde m'appartient un peu."  # expression : yeux brillants
    scene s6_p7 with dissolve
    "Un silence s'installe. Le vent joue dans l'herbe haute. Pierre tourne la bouteille entre ses doigts, comme s'il y cherchait ses mots."  # expression : tension douce
    scene s6_p6 with dissolve
    c_pierre "Eve... tout à l'heure, tu parlais d'un dîner, et moi, j'ai fait celui qui n'avait pas compris. Alors voilà, je me lance : il y a la fête du village, samedi soir. Est-ce que tu voudrais y aller avec moi ?"  # expression : nerveux, sincère
    scene s6_p8 with dissolve
    c_eve "Hmm... La fête du village. Avec la musique, les lampions, et tout le monde qui nous regardera arriver ensemble ?"  # expression : sourire malicieux
    scene s6_p9 with dissolve
    c_eve "Je vais y réfléchir, Pierre. Il faut que je consulte mon emploi du temps, très chargé, tu comprends : les vaches, le fromage, la limonade..."  # expression : air faussement sérieux
    scene s6_p10 with dissolve
    "Pierre baisse les yeux, un peu déçu, puis croise son regard. Dans les yeux d'Eve, il n'y a ni hésitation ni doute : la réponse y est déjà, lumineuse, et il sourit à son tour."  # expression : tendresse
    return

