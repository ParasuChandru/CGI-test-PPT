uses PolicyService

class PolicyHandler {

  function handle() : boolean {
    var service = new PolicyService()
    return service.process()
  }

}
