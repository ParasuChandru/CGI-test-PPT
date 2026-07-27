uses PolicyUtil

class PolicyService {

  function process() : boolean {
    var util = new PolicyUtil()
    return util.validate()
  }

}
